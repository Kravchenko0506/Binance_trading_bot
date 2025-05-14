# services/order_execution.py
import json
import os
from services.binance_client import client
from utils.quantity_utils import get_lot_size, round_step_size
# import config.settings as settings # settings больше не нужны здесь для флагов USE_STOP_LOSS и т.д.
from colorama import Fore, Style
# Убираем импорты функций проверки, так как они здесь больше не нужны
# from utils.profit_check import is_enough_profit, is_stop_loss_triggered, is_take_profit_reached
import asyncio
from utils.notifier import send_notification # send_notification здесь может быть не нужен, если он вызывается из price_processor
from utils.logger import trading_logger, system_logger # Добавим system_logger для ошибок
from utils.position_manager import save_last_buy_price, clear_position, has_open_position


def get_balance(asset):
    """Получает свободный баланс указанного актива."""
    try:
        balance = client.get_asset_balance(asset=asset)
        return float(balance['free'])
    except Exception as e:
        system_logger.error(f"Ошибка получения баланса для {asset}: {e}", exc_info=True)
        # await send_notification(f"❌ Ошибка получения баланса для {asset}. См. логи.") # Уведомления лучше из async контекста
        raise # Пробрасываем ошибку, чтобы place_order мог ее обработать



def place_order(action: str, symbol: str, commission_rate: float): # commission_rate теперь из профиля
    """
    Размещает рыночный ордер на покупку или продажу.
    Логика принятия решения (RSI, MACD, Stop-Loss, Take-Profit, Min-Profit)
    теперь находится ВНЕ этой функции (в price_processor).
    Эта функция только исполняет принятое решение.
    """
    trading_logger.info(f"place_order: Получен запрос: {action} для {symbol}")
    step_size, min_qty = None, None # Инициализация
    try:
        step_size, min_qty = get_lot_size(symbol)
        if step_size is None or min_qty is None: # Проверяем оба значения
            trading_logger.error(f"Не удалось получить LOT_SIZE (step_size или min_qty) для {symbol}. Ордер не будет размещен.")
            # await send_notification(f"❌ Ошибка: Не удалось получить торговые лимиты для {symbol}. Ордер отменен.")
            return # Важно выйти, если нет данных для расчета количества
    except Exception as e:
        trading_logger.error(f"Критическая ошибка при получении LOT_SIZE для {symbol}: {e}", exc_info=True)
        # await send_notification(f"❌ Критическая ошибка торговых лимитов для {symbol}. Ордер отменен.")
        return

    current_price = None
    try:
        # Получаем текущую цену ОДИН РАЗ для расчетов, если это покупка
        # Для продажи цена не так важна для расчета количества, т.к. продаем весь баланс актива
        if action == 'buy':
            current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])
    except Exception as e:
        trading_logger.error(f"Не удалось получить текущую цену для {symbol} при попытке {action}: {e}", exc_info=True)
        # await send_notification(f"❌ Ошибка получения цены для {symbol} перед ордером {action}. Ордер отменен.")
        return # Не можем продолжать без цены для покупки

    quantity = 0.0

    if action == 'buy':
        try:
            usdt_balance = get_balance('USDT')
            if current_price == 0: # Проверка деления на ноль
                trading_logger.error(f"Текущая цена для {symbol} равна 0. Покупка невозможна.")
                return
            # Рассчитываем количество к покупке на основе баланса USDT
            # Учитываем комиссию, чтобы купить на доступный баланс
            # (1 - commission_rate) немного уменьшает сумму, на которую покупаем, чтобы хватило на комиссию
            # Но это не совсем точно, т.к. комиссия берется от суммы сделки.
            # Более точный расчет: quantity_to_buy_with_usdt = usdt_balance / (current_price * (1 + commission_rate))
            # Но для простоты пока оставим твой вариант, он чуть консервативнее.
            raw_quantity = (usdt_balance / current_price) * (1 - commission_rate) # Уменьшаем количество, чтобы хватило на комиссию
            quantity = round_step_size(raw_quantity, step_size)
            trading_logger.info(f"Расчет покупки для {symbol}: Баланс USDT: {usdt_balance}, Цена: {current_price}, raw_qty: {raw_quantity}, округл_qty: {quantity}, min_qty: {min_qty}")

            if quantity >= min_qty:
                # Проверяем, не превышает ли стоимость ордера доступный баланс (примерно)
                # Это очень грубая проверка, т.к. цена может измениться.
                # Binance сама отклонит ордер, если не хватит средств.
                estimated_cost = quantity * current_price 
                if estimated_cost > usdt_balance * 0.99: # Оставляем небольшой запас
                    trading_logger.warning(f"Расчетное количество {quantity} для {symbol} по цене {current_price} (стоимость {estimated_cost}) может превысить баланс USDT {usdt_balance}. Проверьте расчеты.")
                    # Можно не отменять, а позволить Binance решить.

                trading_logger.info(f"Размещение ордера MARKET BUY: {quantity} {symbol}")
                order = client.order_market_buy(symbol=symbol, quantity=quantity)
                # Обработка ответа и логирование покупки
                fills = order.get('fills', [])
                if not fills: # Если ордер размещен, но не исполнен сразу или частично (маловероятно для MARKET)
                    trading_logger.warning(f"Ордер на покупку {symbol} размещен, но нет информации об исполнении (fills). ID ордера: {order.get('orderId')}")
                    # Сохраняем цену запроса, если нет fills (менее точно)
                    save_last_buy_price(symbol, avg_price_filled) # Сохраняем цену, по которой пытались купить
                    # Уведомление об ордере без деталей исполнения
                    asyncio.create_task(send_notification(f"⚠️ Ордер MARKET BUY для {symbol} qty {quantity} размещен, но детали исполнения не получены сразу."))
                    return # Выходим, так как нет деталей для полного лога

                total_qty_filled = sum(float(f.get('qty', 0)) for f in fills)
                total_cost = sum(float(f.get('price', 0)) * float(f.get('qty', 0)) for f in fills)
                avg_price_filled = total_cost / total_qty_filled if total_qty_filled else 0
                
                total_commission = sum(float(f.get('commission', 0)) for f in fills)
                commission_asset = fills[0].get('commissionAsset', '') if fills else ''

                log_message = (f"Покупка: {total_qty_filled:.6f} {symbol.replace('USDT', '')} по средней цене {avg_price_filled:.6f} USDT. "
                               f"Потрачено: {total_cost:.6f} USDT. Комиссия: {total_commission:.6f} {commission_asset}.")
                trading_logger.info(log_message)
                print(Fore.GREEN + log_message + Style.RESET_ALL)
                
                save_last_buy_price(symbol, avg_price_filled) # Сохраняем среднюю цену фактической покупки

                # Уведомление в Telegram (оставляем здесь, так как это результат действия)
                msg_tg = (
                    f"🟢 КУПЛЕНО\n"
                    f"Символ: {symbol}\n"
                    f"Объём: {total_qty_filled:.6f}\n"
                    f"Ср. цена: {avg_price_filled:.4f} USDT\n"
                    f"Сумма: {total_cost:.2f} USDT\n"
                    f"Комиссия: {total_commission:.6f} {commission_asset}"
                )
                asyncio.create_task(send_notification(msg_tg))
            else:
                trading_logger.warning(f"Недостаточно средств или рассчитанное количество ({quantity}) < минимального ({min_qty}) для покупки {symbol}.")
                # asyncio.create_task(send_notification(f"⚠️ Не удалось купить {symbol}: количество {quantity} < мин. {min_qty} или не хватает USDT."))
        except Exception as e:
            trading_logger.error(f"Ошибка при размещении ордера на ПОКУПКУ для {symbol}: {e}", exc_info=True)
            asyncio.create_task(send_notification(f"❌ Ошибка ордера на ПОКУПКУ {symbol}. См. логи."))


    elif action == 'sell':
        try:
            base_asset = symbol.replace('USDT', '') # Определяем базовый актив (например, XRP из XRPUSDT)
            asset_balance = get_balance(base_asset)
            # При продаже мы обычно хотим продать весь доступный баланс этого актива
            # Уменьшение на commission_rate здесь не совсем корректно, т.к. комиссия берется от суммы продажи
            # Лучше продавать весь баланс, а биржа сама учтет комиссию.
            # raw_quantity = asset_balance * (1 - commission_rate) # Эту строку можно убрать
            raw_quantity = asset_balance
            quantity = round_step_size(raw_quantity, step_size)
            trading_logger.info(f"Расчет продажи для {symbol}: Баланс {base_asset}: {asset_balance}, raw_qty: {raw_quantity}, округл_qty: {quantity}, min_qty: {min_qty}")

            if quantity >= min_qty:
                # --- УДАЛЯЕМ ИЗБЫТОЧНЫЕ ПРОВЕРКИ РИСК-МЕНЕДЖМЕНТА ---
                # Решение о продаже по стоп-лоссу/тейк-профиту/мин.профиту
                # уже принято в price_processor ДО вызова place_order.
                # Здесь мы просто исполняем команду 'sell'.

                # if settings.USE_STOP_LOSS and is_stop_loss_triggered(symbol): # УДАЛЕНО
                #     trading_logger.warning(f"❗ Stop-loss: убыток превышает {settings.STOP_LOSS_RATIO*100:.1f}% — принудительная продажа")
                # elif settings.USE_TAKE_PROFIT and is_take_profit_reached(symbol): # УДАЛЕНО
                #     trading_logger.info(f"✅ Take-profit: прибыль превышает {settings.TAKE_PROFIT_RATIO*100:.1f}% — фиксируем")
                # elif settings.USE_MIN_PROFIT and not is_enough_profit(symbol): # УДАЛЕНО
                #     trading_logger.info("📉 Профит слишком мал — отмена продажи")
                #     return # Если продажа отменена по min_profit, выходим

                trading_logger.info(f"Размещение ордера MARKET SELL: {quantity} {symbol}")
                order = client.order_market_sell(symbol=symbol, quantity=quantity)
                # Обработка ответа и логирование продажи
                fills = order.get('fills', [])
                if not fills:
                    trading_logger.warning(f"Ордер на продажу {symbol} размещен, но нет информации об исполнении (fills). ID ордера: {order.get('orderId')}")
                    # Удаляем файл с ценой покупки, так как позиция считается закрытой или в процессе закрытия
                    try:
                        clear_position(symbol)
                        trading_logger.info(f"Файл цены покупки для {symbol} удален после попытки продажи.")
                    except FileNotFoundError:
                        trading_logger.info(f"Файл цены покупки для {symbol} не найден для удаления (возможно, уже удален).")
                    except Exception as e_rem:
                         system_logger.error(f"Ошибка удаления файла цены покупки для {symbol}: {e_rem}", exc_info=True)
                    asyncio.create_task(send_notification(f"⚠️ Ордер MARKET SELL для {symbol} qty {quantity} размещен, но детали исполнения не получены сразу."))
                    return

                total_qty_filled = sum(float(f.get('qty', 0)) for f in fills)
                total_value_received = sum(float(f.get('price', 0)) * float(f.get('qty', 0)) for f in fills)
                avg_price_filled = total_value_received / total_qty_filled if total_qty_filled else 0
                
                total_commission = sum(float(f.get('commission', 0)) for f in fills)
                commission_asset = fills[0].get('commissionAsset', '') if fills else '' # Обычно USDT для продажи

                log_message = (f"Продажа: {total_qty_filled:.6f} {base_asset} по средней цене {avg_price_filled:.6f} USDT. "
                               f"Получено: {total_value_received:.6f} USDT. Комиссия: {total_commission:.6f} {commission_asset}.")
                trading_logger.info(log_message)
                print(Fore.RED + log_message + Style.RESET_ALL)

                # Удаляем файл с ценой последней покупки, так как позиция закрыта
                clear_position(symbol)

                # Уведомление в Telegram
                msg_tg = (
                    f"🔴 ПРОДАНО\n"
                    f"Символ: {symbol}\n"
                    f"Объём: {total_qty_filled:.6f}\n"
                    f"Ср. цена: {avg_price_filled:.4f} USDT\n"
                    f"Сумма: {total_value_received:.2f} USDT\n"
                    f"Комиссия: {total_commission:.6f} {commission_asset}"
                )
                asyncio.create_task(send_notification(msg_tg))
            else:
                trading_logger.warning(f"Недостаточно средств ({asset_balance} {base_asset}, рассчитанное кол-во {quantity}) < минимального ({min_qty}) для продажи {symbol}.")
                # asyncio.create_task(send_notification(f"⚠️ Не удалось продать {symbol}: количество {quantity} < мин. {min_qty} или баланс {base_asset} равен 0."))
        except Exception as e:
            trading_logger.error(f"Ошибка при размещении ордера на ПРОДАЖУ для {symbol}: {e}", exc_info=True)
            asyncio.create_task(send_notification(f"❌ Ошибка ордера на ПРОДАЖУ {symbol}. См. логи."))
    else:
        trading_logger.error(f"Неизвестное действие для ордера: '{action}' для символа {symbol}")




