# services/order_execution.py
import json
import os
import asyncio  # Для asyncio.to_thread
from decimal import Decimal, ROUND_DOWN  # Для точной работы с числами
from typing import Optional

from services.binance_client import client  # Клиент Binance
# Утилиты для расчета количества
from utils.quantity_utils import get_lot_size, round_step_size
import config.settings as settings  # Глобальные настройки
from colorama import Fore, Style  # Для цветного вывода в консоль
from utils.profit_check import save_last_buy_price, get_last_buy_price_path
from utils.notifier import send_notification  # Асинхронные уведомления
from utils.logger import trading_logger, system_logger  # Логгеры


async def get_asset_balance_async(asset: str) -> Optional[Decimal]:
    # ... (твой существующий код get_asset_balance_async)
    try:
        for attempt in range(3):
            balance_info = await asyncio.to_thread(client.get_asset_balance, asset=asset)
            if balance_info is not None:
                break
            await asyncio.sleep(2)
        else:
            trading_logger.error(
                f"Order Execution: Баланс не получен для  {asset} после 3 попыток, возвращаю 0.")
            return None

        if balance_info and 'free' in balance_info:
            return Decimal(balance_info['free'])
        trading_logger.warning(
            f"Order Execution: Не удалось получить 'free' баланс для {asset}, ответ: {balance_info}")
        return Decimal('0')  # Возвращаем 0 если 'free' нет
    except Exception as e:
        trading_logger.error(
            f"Order Execution: Ошибка при получении баланса для {asset}: {e}", exc_info=True)
        return None  # Возвращаем None в случае других ошибок


async def place_order_async(
    symbol: str,
    action: str,  # 'buy' or 'sell'
    quantity_to_trade: Decimal,
    order_type: str,  # 'MARKET' или 'LIMIT'
    # Цена для LIMIT ордера или ТЕКУЩАЯ РЫНОЧНАЯ для MARKET SELL (для проверки)
    limit_price: Optional[Decimal] = None,
    stop_price: Optional[Decimal] = None,
    profile_name: Optional[str] = "default"
) -> Optional[dict]:
    """
    Асинхронно размещает ордер на покупку или продажу с учетом всех проверок и логики.
    Использует Decimal для всех расчетов, связанных с ценой и количеством.
    """
    qty_str = f"{quantity_to_trade:.8f}" if isinstance(
        quantity_to_trade, Decimal) else str(quantity_to_trade)
    limit_price_str = f"{limit_price:.8f}" if limit_price else "N/A"

    # --- НАЧАЛО БЛОКА ЛОГИРОВАНИЯ ДЛЯ ДИАГНОСТИКИ ---
    trading_logger.info(
        f"place_order_async ВЫЗВАН для {symbol}: action={action}, quantity_to_trade={qty_str}, "
        f"order_type={order_type}, limit_price_ARG={limit_price_str}, profile={profile_name}"
    )
    # --- КОНЕЦ БЛОКА ЛОГИРОВАНИЯ ДЛЯ ДИАГНОСТИКИ ---

    lot_size_info = await asyncio.to_thread(get_lot_size, symbol)
    if not lot_size_info:
        trading_logger.error(
            f"Order Execution ({symbol}): Не удалось получить информацию о лоте. Ордер отменен.")
        await send_notification(f"❌ Ошибка ордера {action.upper()} для {symbol}: Не получена информация о лоте.")
        return None

    min_qty = Decimal(lot_size_info['minQty'])
    step_size = Decimal(lot_size_info['stepSize'])
    base_asset = lot_size_info['baseAsset']
    quote_asset = lot_size_info['quoteAsset']
    precision_amount = int(lot_size_info['precision_amount'])
    precision_price = int(lot_size_info['precision_price'])

    if not isinstance(quantity_to_trade, Decimal):
        quantity_to_trade = Decimal(str(quantity_to_trade))

    rounded_quantity = round_step_size(quantity_to_trade, step_size)

    # Пропускаем проверку если quantity_to_trade == 0 (например, при ошибке расчета)
    if rounded_quantity < min_qty and rounded_quantity > Decimal('0'):
        trading_logger.warning(
            f"Order Execution ({symbol}): Рассчитанное количество {rounded_quantity:.8f} {base_asset} "
            f"меньше минимально допустимого ({min_qty:.8f} {base_asset}). Действие '{action}' отменено."
        )
        return None
    if rounded_quantity == Decimal('0'):
        trading_logger.error(
            f"Order Execution ({symbol}): Количество для торговли равно 0 для {action}. Ордер отменен.")
        return None

    order_response = None

    if action.lower() == 'buy':
        # ... (существующая логика покупки: проверка баланса, расчет стоимости и т.д.)
        # ВАЖНО: Убедись, что save_last_buy_price и position_manager.update_position вызываются корректно ПОСЛЕ УСПЕШНОЙ ПОКУПКИ
        # Примерно так, как было в твоем коде (я добавил avg_executed_price):
        trading_logger.info(
            f"Order Execution ({symbol}): Инициация покупки {rounded_quantity:.{precision_amount}f} {base_asset}...")
        try:
            quote_asset_balance = await get_asset_balance_async(quote_asset)
            if quote_asset_balance is None:  # Ошибка получения баланса
                trading_logger.error(
                    f"Order Execution ({symbol}): Не удалось получить баланс {quote_asset}. Покупка отменена.")
                await send_notification(f"❌ Ошибка ордера BUY для {symbol}: Не удалось получить баланс {quote_asset}.")
                return None

            estimated_cost = Decimal('0')
            # Предполагаем, что limit_price - это текущая цена для MARKET
            current_price_for_buy_check = limit_price

            if order_type.upper() == 'MARKET':
                if current_price_for_buy_check is None or current_price_for_buy_check <= Decimal('0'):
                    trading_logger.error(
                        f"Order Execution ({symbol}): Для MARKET BUY не передана текущая цена (через limit_price). Невозможно оценить стоимость. Покупка отменена.")
                    return None
                estimated_cost = rounded_quantity * current_price_for_buy_check
            elif order_type.upper() == 'LIMIT':
                if limit_price is None or limit_price <= Decimal('0'):
                    trading_logger.error(
                        f"Order Execution ({symbol}): Для LIMIT BUY не указана корректная цена. Покупка отменена.")
                    return None
                estimated_cost = rounded_quantity * limit_price

            if quote_asset_balance < estimated_cost:
                trading_logger.error(
                    f"Order Execution ({symbol}): Недостаточно средств на балансе {quote_asset}. "
                    f"Требуется: ~{estimated_cost:.8f}, Доступно: {quote_asset_balance:.8f}. Покупка отменена."
                )
                await send_notification(
                    f"❌ Ордер BUY для {symbol} отменен: недостаточно {quote_asset}. "
                    f"Надо: ~{estimated_cost:.2f}, есть: {quote_asset_balance:.2f}"
                )
                return None

            order_params = {
                'symbol': symbol, 'side': client.SIDE_BUY, 'type': order_type.upper(),
                'quantity': f"{rounded_quantity:.{precision_amount}f}"
            }
            if order_type.upper() == 'LIMIT':
                order_params['price'] = f"{limit_price:.{precision_price}f}"
                order_params['timeInForce'] = client.TIME_IN_FORCE_GTC

            trading_logger.info(
                f"Order Execution ({symbol}): Отправка {order_type.upper()} BUY ордера: {order_params}")
            order_response = await asyncio.to_thread(client.create_order, **order_params)
            trading_logger.info(
                f"Order Execution ({symbol}): Ответ на ордер BUY: {json.dumps(order_response, indent=2)}")

            if order_response and order_response.get('status') == 'FILLED':
                executed_qty_str = order_response.get('executedQty', '0')
                cummulative_quote_qty_str = order_response.get(
                    'cummulativeQuoteQty', '0')
                executed_qty = Decimal(executed_qty_str)
                cummulative_quote_qty = Decimal(cummulative_quote_qty_str)

                avg_executed_price = Decimal('0')
                if executed_qty > Decimal('0'):
                    avg_executed_price = (
                        cummulative_quote_qty / executed_qty).quantize(Decimal('1e-{}'.format(precision_price)))

                commission_total = Decimal('0')
                commission_asset_str = base_asset  # По умолчанию
                if order_response.get('fills'):
                    for fill in order_response['fills']:
                        commission_total += Decimal(fill['commission'])
                        commission_asset_str = fill['commissionAsset']

                trading_logger.info(
                    f"✅ ПОКУПКА ({symbol}): {executed_qty:.{precision_amount}f} {base_asset} @ ~{avg_executed_price:.{precision_price}f} {quote_asset}. "
                    f"Потрачено: {cummulative_quote_qty:.8f} {quote_asset}. Комиссия: {commission_total:.8f} {commission_asset_str}."
                )
                await send_notification(
                    f"🟢 КУПЛЕНО: {executed_qty:.4f} {base_asset} для {symbol} @ ~{avg_executed_price:.4f} {quote_asset}\n"
                    f"Комиссия: {commission_total:.6f} {commission_asset_str}"
                )
                save_last_buy_price(symbol, float(avg_executed_price), float(
                    executed_qty), profile_name if profile_name else "unknown_profile")
                # Здесь тебе нужно будет импортировать и использовать твой position_manager
                # from utils.position_manager import position_manager # Сделай это в начале файла
                # position_manager.update_position(...) # Раскомментируй и используй, если он глобальный
                # или передавай его как аргумент, как мы обсуждали для Пути 2
            # ... (остальная обработка ответа на покупку) ...
        except Exception as e:
            trading_logger.error(
                f"Order Execution ({symbol}): Ошибка при размещении ордера BUY: {e}", exc_info=True)
            await send_notification(f"❌ Ошибка ордера BUY для {symbol}: {e}")
            order_response = None

    elif action.lower() == 'sell':
        trading_logger.info(
            f"Order Execution ({symbol}): Инициация продажи {rounded_quantity:.{precision_amount}f} {base_asset}...")
        base_asset_balance = await get_asset_balance_async(base_asset)

        # Убеждаемся, что количество для продажи не превышает доступный баланс
        # и что оно соответствует тому, что мы хотим продать (rounded_quantity)
        if base_asset_balance is None:
            trading_logger.error(
                f"Order Execution ({symbol}): Не удалось получить баланс {base_asset} для продажи. Продажа отменена.")
            return None
        if rounded_quantity > base_asset_balance:
            trading_logger.warning(
                f"Order Execution ({symbol}): Количество для продажи ({rounded_quantity:.{precision_amount}f}) "
                f"превышает доступный баланс ({base_asset_balance:.{precision_amount}f} {base_asset}). "
                f"Продаем доступный баланс."
            )
            rounded_quantity = round_step_size(
                base_asset_balance, step_size)  # Округляем доступный баланс
            if rounded_quantity < min_qty:
                trading_logger.warning(
                    f"Order Execution ({symbol}): Доступный баланс {base_asset_balance} после округления {rounded_quantity} меньше min_qty {min_qty}. Продажа отменена.")
                return None

        if rounded_quantity < min_qty:  # Проверка после возможной коррекции по балансу
            trading_logger.warning(
                f"Order Execution ({symbol}): Рассчитанное количество для продажи {rounded_quantity:.{precision_amount}f} {base_asset} "
                f"меньше минимально допустимого ({min_qty:.{precision_amount}f} {base_asset}). Продажа отменена."
            )
            return None

        # --- НАЧАЛО БЛОКА ЛОГИРОВАНИЯ ДЛЯ ДИАГНОСТИКИ ЗАЩИТЫ ОТ УБЫТКА ---
        buy_price_file_path = get_last_buy_price_path(
            symbol, profile_name if profile_name else "unknown_profile")
        last_buy_info = None
        if os.path.exists(buy_price_file_path):
            try:
                with open(buy_price_file_path, 'r') as f:
                    last_buy_info = json.load(f)
            except Exception as e_load:
                trading_logger.error(
                    f"Order Execution ({symbol}): Ошибка загрузки файла цены покупки '{buy_price_file_path}': {e_load}")

        # Цена, с которой будем сравнивать цену покупки
        price_to_check_against_buy = Decimal('0')

        if order_type.upper() == 'MARKET':
            # limit_price используется для передачи current_market_price
            if limit_price is not None and limit_price > Decimal('0'):
                price_to_check_against_buy = limit_price
                trading_logger.info(
                    f"Order Execution ({symbol}): Для MARKET SELL используем переданную рыночную цену для проверки: {price_to_check_against_buy:.{precision_price}f}")
            else:
                trading_logger.warning(
                    f"Order Execution ({symbol}): Для MARKET SELL не передана текущая рыночная цена (через аргумент limit_price) для проверки защиты от убытка. "
                    f"Защита от продажи в убыток НЕ БУДЕТ ВЫПОЛНЕНА."
                )
                # Если цена для проверки не предоставлена, мы не можем выполнить защиту.
                # Продолжаем без нее, но это рискованно.
        elif order_type.upper() == 'LIMIT':
            if limit_price is None or limit_price <= Decimal('0'):
                trading_logger.error(
                    f"Order Execution ({symbol}): Для LIMIT SELL не указана корректная цена (в limit_price). Продажа отменена.")
                return None
            # Для LIMIT ордера сравниваем с ценой лимита
            price_to_check_against_buy = limit_price
            trading_logger.info(
                f"Order Execution ({symbol}): Для LIMIT SELL используем цену лимита для проверки: {price_to_check_against_buy:.{precision_price}f}")

        if last_buy_info:
            try:
                last_buy_price_from_file = Decimal(str(last_buy_info['price']))
                # buy_quantity_from_file = Decimal(str(last_buy_info.get('quantity', '0.0'))) # Можем использовать позже, если нужно

                trading_logger.info(
                    f"ПРОВЕРКА ПЕРЕД ПРОДАЖЕЙ ({symbol}):\n"
                    f"  Цена покупки из файла (last_buy_price_from_file): {last_buy_price_from_file:.{precision_price}f}\n"
                    f"  Цена для проверки продажи (price_to_check_against_buy): {price_to_check_against_buy:.{precision_price}f}\n"
                    f"  settings.USE_PAPER_TRADING: {settings.USE_PAPER_TRADING}"
                )

                # Только если есть актуальная цена для проверки
                if price_to_check_against_buy > Decimal('0'):
                    check1_not_paper_trading = not settings.USE_PAPER_TRADING
                    check2_price_lower = price_to_check_against_buy < last_buy_price_from_file

                    trading_logger.info(
                        f"ПОДУСЛОВИЯ для отмены продажи ({symbol}):\n"
                        f"  (not settings.USE_PAPER_TRADING) IS {check1_not_paper_trading}\n"
                        f"  (price_to_check_against_buy < last_buy_price_from_file) IS {check2_price_lower} "
                        f"({price_to_check_against_buy:.{precision_price}f} < {last_buy_price_from_file:.{precision_price}f})"
                    )

                    if check1_not_paper_trading and check2_price_lower:
                        trading_logger.warning(
                            f"🚫 ОТМЕНА ПРОДАЖИ ({symbol}): Цена проверки ({price_to_check_against_buy:.{precision_price}f}) "
                            f"НИЖЕ цены покупки ({last_buy_price_from_file:.{precision_price}f}). Защита сработала."
                        )
                        return None  # Отменяем продажу
                    else:
                        trading_logger.info(
                            f"Условие отмены продажи НЕ ВЫПОЛНЕНО для {symbol}. Продажа РАЗРЕШЕНА."
                        )
                else:
                    trading_logger.warning(
                        f"Order Execution ({symbol}): Нет актуальной цены для проверки (price_to_check_against_buy = 0). "
                        f"Продажа продолжается без ценовой защиты от убытков. ЭТО РИСК!"
                    )
            except (ValueError, TypeError, KeyError) as e:
                trading_logger.error(
                    f"Order Execution ({symbol}): Ошибка данных в файле цены покупки '{buy_price_file_path}' при проверке: {e}. Содержимое: {last_buy_info}"
                )
                await send_notification(f"⚠️ Ошибка данных о покупке для {symbol}. Продажа отменена для безопасности.")
                return None
        else:
            trading_logger.warning(
                f"Информация для ПРОДАЖИ ({symbol}): Файл цены покупки '{buy_price_file_path}' не найден. "
                f"Продажа без проверки цены покупки."
            )
        # --- КОНЕЦ БЛОКА ЛОГИРОВАНИЯ ДЛЯ ДИАГНОСТИКИ ЗАЩИТЫ ОТ УБЫТКА ---

        # Если все проверки пройдены, размещаем ордер на продажу
        try:
            order_params = {
                'symbol': symbol, 'side': client.SIDE_SELL, 'type': order_type.upper(),
                'quantity': f"{rounded_quantity:.{precision_amount}f}"
            }
            if order_type.upper() == 'LIMIT':
                # Доп. проверка для LIMIT перед отправкой
                if limit_price is None or limit_price <= Decimal('0'):
                    trading_logger.error(
                        f"Order Execution ({symbol}): Попытка отправить LIMIT SELL без корректной limit_price. Ордер отменен.")
                    return None
                order_params['price'] = f"{limit_price:.{precision_price}f}"
                order_params['timeInForce'] = client.TIME_IN_FORCE_GTC

            trading_logger.info(
                f"Order Execution ({symbol}): Отправка {order_type.upper()} SELL ордера: {order_params}")
            order_response = await asyncio.to_thread(client.create_order, **order_params)
            trading_logger.info(
                f"Order Execution ({symbol}): Ответ на ордер SELL: {json.dumps(order_response, indent=2)}")

            if order_response and order_response.get('status') == 'FILLED':
                # ... (существующая логика обработки успешной продажи) ...
                # Важно: Убедись, что delete_last_buy_price и position_manager.clear_position вызываются здесь
                executed_qty_str = order_response.get('executedQty', '0')
                cummulative_quote_qty_str = order_response.get(
                    'cummulativeQuoteQty', '0')
                executed_qty = Decimal(executed_qty_str)
                cummulative_quote_qty = Decimal(cummulative_quote_qty_str)

                avg_executed_price = Decimal('0')
                if executed_qty > Decimal('0'):
                    avg_executed_price = (
                        cummulative_quote_qty / executed_qty).quantize(Decimal('1e-{}'.format(precision_price)))

                commission_total = Decimal('0')
                commission_asset_str = quote_asset
                if order_response.get('fills'):
                    for fill in order_response['fills']:
                        commission_total += Decimal(fill['commission'])
                        commission_asset_str = fill['commissionAsset']

                trading_logger.info(
                    f"✅ ПРОДАЖА ({symbol}): {executed_qty:.{precision_amount}f} {base_asset} @ ~{avg_executed_price:.{precision_price}f} {quote_asset}. "
                    f"Получено: {cummulative_quote_qty:.8f} {quote_asset}. Комиссия: {commission_total:.8f} {commission_asset_str}."
                )
                await send_notification(
                    f"🔴 ПРОДАНО: {executed_qty:.4f} {base_asset} для {symbol} @ ~{avg_executed_price:.4f} {quote_asset}\n"
                    f"Комиссия: {commission_total:.6f} {commission_asset_str}"
                )

                if os.path.exists(buy_price_file_path):
                    try:
                        await asyncio.to_thread(os.remove, buy_price_file_path)
                        trading_logger.info(
                            f"Order Execution ({symbol}): Файл цены покупки '{buy_price_file_path}' удален после продажи.")
                    except OSError as e_remove:
                        trading_logger.error(
                            f"Order Execution ({symbol}): Не удалось удалить файл цены покупки '{buy_price_file_path}': {e_remove}")
                # Здесь тебе нужно будет импортировать и использовать твой position_manager
                # from utils.position_manager import position_manager # Сделай это в начале файла
                # position_manager.clear_position(symbol) # Раскомментируй и используй, если он глобальный
            # ... (остальная обработка ответа на продажу) ...
        except Exception as e:
            trading_logger.error(
                f"Order Execution ({symbol}): Ошибка при размещении ордера SELL: {e}", exc_info=True)
            await send_notification(f"❌ Ошибка ордера SELL для {symbol}: {e}")
            order_response = None

    else:
        trading_logger.error(
            f"Order Execution ({symbol}): Неизвестное действие '{action}'. Допустимы 'buy' или 'sell'.")
        return None

    return order_response
