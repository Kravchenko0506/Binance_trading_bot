# services/order_execution.py
import json
import os
import asyncio # Для asyncio.to_thread
from decimal import Decimal, ROUND_DOWN # Для точной работы с числами

from services.binance_client import client # Клиент Binance
from utils.quantity_utils import get_lot_size, round_step_size # Утилиты для расчета количества
import config.settings as settings # Глобальные настройки
from colorama import Fore, Style # Для цветного вывода в консоль
from utils.profit_check import save_last_buy_price,get_last_buy_price_path 
from utils.notifier import send_notification # Асинхронные уведомления
from utils.logger import trading_logger, system_logger # Логгеры



async def get_asset_balance_async(asset: str) -> Decimal:
    """
    Асинхронно получает СВОБОДНЫЙ баланс указанного актива.
    Возвращает Decimal для точности. В случае ошибки возвращает Decimal('0').
    """
    try:
        # client.get_asset_balance - блокирующий вызов
        balance_info = await asyncio.to_thread(client.get_asset_balance, asset=asset)
        free_balance_str = balance_info.get('free', '0')
        # trading_logger.debug(f"Order Execution: Баланс {asset} из API: {free_balance_str}")
        return Decimal(free_balance_str)
    except Exception as e:
        trading_logger.error(f"Order Execution: Ошибка при получении баланса для {asset}: {e}", exc_info=True)
        await send_notification(f"⚠️ Ошибка API: Не удалось получить баланс {asset}. Проверьте логи.")
        return Decimal('0')


async def get_current_market_price_async(symbol: str) -> Decimal | None:
    """
    Асинхронно получает текущую рыночную цену для символа.
    Возвращает Decimal или None в случае ошибки.
    """
    try:
        # client.get_symbol_ticker - блокирующий вызов
        ticker_info = await asyncio.to_thread(client.get_symbol_ticker, symbol=symbol)
        price_str = ticker_info.get('price')
        if price_str:
            # trading_logger.debug(f"Order Execution: Текущая цена {symbol} из API: {price_str}")
            return Decimal(price_str)
        else:
            trading_logger.error(f"Order Execution: API не вернуло цену для {symbol}. Ответ: {ticker_info}")
            return None
    except Exception as e:
        trading_logger.error(f"Order Execution: Ошибка при получении текущей цены для {symbol}: {e}", exc_info=True)
        await send_notification(f"⚠️ Ошибка API: Не удалось получить цену для {symbol}. Проверьте логи.")
        return None


async def place_order(action: str, symbol: str, profile: object) -> dict | None:
    """
    Асинхронно размещает рыночный ордер на покупку или продажу.
    Возвращает ответ от биржи (словарь) в случае успеха, или None в случае ошибки.

    Args:
        action (str): 'buy' или 'sell'.
        symbol (str): Торговый символ (например, 'XRPUSDT').
        profile (object): Объект профиля, содержащий настройки, включая MIN_TRADE_AMOUNT.
                          Ожидается, что у profile есть атрибут profile.MIN_TRADE_AMOUNT.
    """
    trading_logger.info(f"Order Execution ({symbol}): Инициировано размещение ордера '{action}'...")
    
    base_asset, quote_asset = "", ""
    # Определение базового и квотируемого актива (например, XRP и USDT для XRPUSDT)
    # Это нужно для корректного получения балансов и имен активов
    # Обычно USDT идет вторым. Если нет, логику нужно будет усложнить.
    if symbol.endswith("USDT"):
        base_asset = symbol[:-4]
        quote_asset = "USDT"
    elif symbol.endswith("BUSD"): # Пример для других квот
        base_asset = symbol[:-4]
        quote_asset = "BUSD"
    # Добавить другие популярные квотируемые активы при необходимости (BTC, ETH, etc.)
    else:
        trading_logger.error(f"Order Execution ({symbol}): Не удалось определить базовый и квотируемый актив из символа '{symbol}'. Ордер отменен.")
        await send_notification(f"❌ Ошибка конфигурации: Неизвестный формат символа {symbol} для определения активов.")
        return None

    # Асинхронное получение параметров лота
    try:
        step_size_str, min_qty_str = await asyncio.to_thread(get_lot_size, symbol)
        if step_size_str is None or min_qty_str is None: # get_lot_size мог вернуть None, None
            trading_logger.error(f"Order Execution ({symbol}): Не удалось получить LOT_SIZE. Ордер '{action}' отменен.")
            # Уведомление уже должно быть отправлено из get_lot_size или обертки над ним
            return None
        step_size = Decimal(step_size_str)
        min_qty = Decimal(min_qty_str)
    except Exception as e:
        trading_logger.error(f"Order Execution ({symbol}): Ошибка при получении или обработке LOT_SIZE: {e}", exc_info=True)
        await send_notification(f"❌ Ошибка API: Не удалось получить LOT_SIZE для {symbol}. Ордер '{action}' отменен.")
        return None

    order_response = None
    
    if action == 'buy':
        quote_balance = await get_asset_balance_async(quote_asset) # Баланс в USDT, BUSD и т.д.
        
        if quote_balance <= Decimal('0'):
            trading_logger.warning(f"Order Execution ({symbol}): Недостаточно средств {quote_asset} для покупки (баланс: {quote_balance}).")
            await send_notification(f"ℹ️ Попытка покупки {symbol}: недостаточно {quote_asset} (баланс {quote_balance}).")
            return None

        current_price = await get_current_market_price_async(symbol)
        if current_price is None or current_price <= Decimal('0'):
            trading_logger.error(f"Order Execution ({symbol}): Не удалось получить корректную текущую цену ({current_price}). Покупка отменена.")
            return None
            
        # Определяем, сколько USDT/BUSD потратить. Используем почти весь баланс квотируемого актива.
        # Учитываем минимальную сумму ордера (например, 5 USDT для Binance)
        min_trade_amount_profile = Decimal(str(getattr(profile, 'MIN_TRADE_AMOUNT', settings.MIN_TRADE_AMOUNT)))

        amount_to_spend_in_quote = quote_balance
        if amount_to_spend_in_quote < min_trade_amount_profile:
            trading_logger.warning(
                f"Order Execution ({symbol}): Сумма для покупки {amount_to_spend_in_quote:.8f} {quote_asset} "
                f"меньше минимально допустимой по профилю/настройкам ({min_trade_amount_profile:.2f} {quote_asset}). Покупка отменена."
            )
            await send_notification(f"ℹ️ Попытка покупки {symbol}: сумма {amount_to_spend_in_quote:.2f} {quote_asset} меньше минимальной.")
            return None

        # Рассчитываем количество базового актива для покупки
        # quantity = (amount_to_spend_in_quote / current_price) # Это даст максимальное количество
        # Binance для MARKET ордера при указании quantity ожидает количество базового актива.
        # Можно использовать quoteOrderQty, чтобы указать сумму в USDT, которую хотим потратить.
        # Если использовать quantity, нужно быть осторожным с комиссией и точностью.
        # Попробуем использовать quoteOrderQty, если это более надежно.
        # Для данного кода, где используется round_step_size, мы считаем quantity.
        
        # Уменьшим немного сумму для учета возможной комиссии, если она платится из quote_asset
        # и для предотвращения ошибки "insufficient balance" из-за округлений.
        # Это не самый точный способ, но для рыночных ордеров может сработать.
        effective_amount_to_spend = amount_to_spend_in_quote * Decimal('0.995') # Тратим 99.5%
        
        if effective_amount_to_spend < min_trade_amount_profile:
             trading_logger.warning(f"Order Execution ({symbol}): Эффективная сумма для покупки {effective_amount_to_spend:.8f} {quote_asset} стала меньше минимальной после резерва. Покупка отменена.")
             return None

        raw_quantity_to_buy = effective_amount_to_spend / current_price
        
        # Округляем количество до разрешенного биржей шага (step_size)
        # round_step_size должна корректно работать с Decimal
        quantity_to_buy = round_step_size(raw_quantity_to_buy, step_size) # round_step_size должна вернуть Decimal

        trading_logger.info(f"Order Execution ({symbol}): Расчет покупки: Баланс {quote_asset}={quote_balance:.8f}, Цена={current_price:.8f}, "
                            f"Сумма для траты ({quote_asset})={effective_amount_to_spend:.8f}, "
                            f"Расчетное кол-во={raw_quantity_to_buy:.8f}, Округленное кол-во={quantity_to_buy:.8f} {base_asset}, "
                            f"MinQty={min_qty:.8f}, StepSize={step_size:.8f}")

        if quantity_to_buy >= min_qty:
            try:
                trading_logger.info(f"Order Execution ({symbol}): Отправка MARKET BUY ордера на {quantity_to_buy} {base_asset}.")
                # client.order_market_buy - блокирующий вызов
                order_response = await asyncio.to_thread(
                    client.order_market_buy,
                    symbol=symbol,
                    quantity=float(quantity_to_buy) # API может ожидать float
                )
                trading_logger.info(f"Order Execution ({symbol}): Ответ на ордер BUY: {order_response}")
                
                # Обработка успешного ордера и сохранение цены покупки
                fills = order_response.get('fills', [])
                if fills:
                    total_qty_filled = Decimal('0')
                    weighted_sum_price = Decimal('0')
                    total_commission_paid = Decimal('0')
                    commission_asset = ""

                    for fill in fills:
                        fill_qty = Decimal(fill.get('qty', '0'))
                        fill_price = Decimal(fill.get('price', '0'))
                        total_qty_filled += fill_qty
                        weighted_sum_price += fill_qty * fill_price
                        total_commission_paid += Decimal(fill.get('commission', '0'))
                        if not commission_asset: # Берем из первого филла
                            commission_asset = fill.get('commissionAsset', '')
                    
                    if total_qty_filled > Decimal('0'):
                        avg_price_filled = weighted_sum_price / total_qty_filled
                        # Сохраняем среднюю цену исполнения
                        save_last_buy_price(symbol, float(avg_price_filled)) # profit_check ожидает float
                        
                        spent_quote_asset = avg_price_filled * total_qty_filled # Сколько фактически потрачено USDT

                        log_msg = (
                            f"✅ ПОКУПКА ({symbol}): {total_qty_filled:.8f} {base_asset} "
                            f"@ ~{avg_price_filled:.8f} {quote_asset}. "
                            f"Потрачено: {spent_quote_asset:.8f} {quote_asset}. "
                            f"Комиссия: {total_commission_paid:.8f} {commission_asset}."
                        )
                        trading_logger.info(log_msg)
                        print(Fore.GREEN + log_msg + Style.RESET_ALL)
                        await send_notification(f"🟢 КУПЛЕНО: {total_qty_filled:.6f} {base_asset} для {symbol} @ ~{avg_price_filled:.6f} {quote_asset}")
                    else:
                        trading_logger.warning(f"Order Execution ({symbol}): Ордер BUY выполнен, но не найдено исполненных частей (fills) или нулевое количество.")
                else:
                    trading_logger.warning(f"Order Execution ({symbol}): Ордер BUY размещен, но fills отсутствуют в ответе: {order_response}")

            except Exception as e:
                trading_logger.error(f"Order Execution ({symbol}): Ошибка при размещении ордера BUY: {e}", exc_info=True)
                await send_notification(f"❌ Ошибка ордера BUY для {symbol}: {e}")
                order_response = None # Явный сброс в случае ошибки
        else:
            trading_logger.warning(
                f"Order Execution ({symbol}): Рассчитанное количество для покупки {quantity_to_buy:.8f} {base_asset} "
                f"меньше минимально допустимого ({min_qty:.8f} {base_asset}). Покупка отменена."
            )
            await send_notification(f"ℹ️ Попытка покупки {symbol}: рассчитанное кол-во {quantity_to_buy:.8f} меньше мин. {min_qty:.8f}.")

    elif action == 'sell':
        base_asset_balance = await get_asset_balance_async(base_asset) # Баланс в XRP, BTC и т.д.

        if base_asset_balance <= Decimal('0'):
            trading_logger.warning(f"Order Execution ({symbol}): Нет {base_asset} для продажи (баланс: {base_asset_balance}).")
            # Уведомление здесь может быть излишним, если это штатная ситуация (нет актива для продажи)
            return None
            
        # Количество для продажи - это весь доступный баланс базового актива, округленный по step_size
        quantity_to_sell = round_step_size(base_asset_balance, step_size) # round_step_size должна вернуть Decimal

        trading_logger.info(f"Order Execution ({symbol}): Расчет продажи: Баланс {base_asset}={base_asset_balance:.8f}, "
                            f"Кол-во для продажи={quantity_to_sell:.8f} {base_asset}, "
                            f"MinQty={min_qty:.8f}, StepSize={step_size:.8f}")

        if quantity_to_sell >= min_qty:
            try:
                # Проверка, не превышает ли объем продажи минимальный размер ордера в USDT эквиваленте
                # Это важно, т.к. слишком маленькая продажа может быть отклонена биржей
                current_price_for_sell_check = await get_current_market_price_async(symbol)
                if current_price_for_sell_check and current_price_for_sell_check > Decimal('0'):
                    estimated_sell_value_in_quote = quantity_to_sell * current_price_for_sell_check
                    min_trade_amount_profile = Decimal(str(getattr(profile, 'MIN_TRADE_AMOUNT', settings.MIN_TRADE_AMOUNT)))
                    if estimated_sell_value_in_quote < min_trade_amount_profile:
                        trading_logger.warning(
                            f"Order Execution ({symbol}): Расчетная стоимость продажи {quantity_to_sell:.8f} {base_asset} "
                            f"({estimated_sell_value_in_quote:.8f} {quote_asset}) меньше минимальной суммы сделки "
                            f"({min_trade_amount_profile:.2f} {quote_asset}). Продажа отменена."
                        )
                        # Можно отправить уведомление, если это неожиданно
                        # await send_notification(f"ℹ️ Попытка продажи {symbol}: сумма ({estimated_sell_value_in_quote:.2f} {quote_asset}) меньше минимальной.")
                        return False
                else:
                    trading_logger.warning(f"Order Execution ({symbol}): Не удалось получить цену для проверки мин. суммы продажи. Продолжаем с осторожностью.")
                
                trading_logger.info(f"Order Execution ({symbol}): Отправка MARKET SELL ордера на {quantity_to_sell} {base_asset}.")
                # client.order_market_sell - блокирующий вызов
                order_response = await asyncio.to_thread(
                    client.order_market_sell,
                    symbol=symbol,
                    quantity=float(quantity_to_sell) # API может ожидать float
                )
                trading_logger.info(f"Order Execution ({symbol}): Ответ на ордер SELL: {order_response}")

                # Обработка успешного ордера на продажу
                fills = order_response.get('fills', [])
                if fills:
                    total_qty_filled = Decimal('0')
                    weighted_sum_price = Decimal('0')
                    total_commission_paid = Decimal('0')
                    commission_asset = ""

                    for fill in fills:
                        fill_qty = Decimal(fill.get('qty', '0'))
                        fill_price = Decimal(fill.get('price', '0'))
                        total_qty_filled += fill_qty
                        weighted_sum_price += fill_qty * fill_price
                        total_commission_paid += Decimal(fill.get('commission', '0'))
                        if not commission_asset:
                            commission_asset = fill.get('commissionAsset', '')
                    
                    if total_qty_filled > Decimal('0'):
                        avg_price_filled = weighted_sum_price / total_qty_filled
                        received_quote_asset = avg_price_filled * total_qty_filled # Сколько фактически получено USDT/BUSD

                        log_msg = (
                            f"✅ ПРОДАЖА ({symbol}): {total_qty_filled:.8f} {base_asset} "
                            f"@ ~{avg_price_filled:.8f} {quote_asset}. "
                            f"Получено: {received_quote_asset:.8f} {quote_asset}. "
                            f"Комиссия: {total_commission_paid:.8f} {commission_asset}."
                        )
                        trading_logger.info(log_msg)
                        print(Fore.RED + log_msg + Style.RESET_ALL)
                        await send_notification(f"🔴 ПРОДАНО: {total_qty_filled:.6f} {base_asset} для {symbol} @ ~{avg_price_filled:.6f} {quote_asset}")
                        
                        # После успешной продажи можно удалить файл с ценой покупки
                        # чтобы следующая покупка не ориентировалась на старую цену для profit_check
                        buy_price_file = get_last_buy_price_path(symbol)
                        if os.path.exists(buy_price_file):
                            try:
                                os.remove(buy_price_file)
                                trading_logger.info(f"Order Execution ({symbol}): Файл цены покупки '{buy_price_file}' удален после продажи.")
                            except OSError as e_remove:
                                trading_logger.error(f"Order Execution ({symbol}): Не удалось удалить файл цены покупки '{buy_price_file}': {e_remove}")
                    else:
                        trading_logger.warning(f"Order Execution ({symbol}): Ордер SELL выполнен, но не найдено исполненных частей (fills) или нулевое количество.")
                else:
                    trading_logger.warning(f"Order Execution ({symbol}): Ордер SELL размещен, но fills отсутствуют в ответе: {order_response}")
            
            except Exception as e:
                trading_logger.error(f"Order Execution ({symbol}): Ошибка при размещении ордера SELL: {e}", exc_info=True)
                await send_notification(f"❌ Ошибка ордера SELL для {symbol}: {e}")
                order_response = None
        else:
            trading_logger.warning(
                f"Order Execution ({symbol}): Рассчитанное количество для продажи {quantity_to_sell:.8f} {base_asset} "
                f"меньше минимально допустимого ({min_qty:.8f} {base_asset}). Продажа отменена."
            )
            # Уведомление здесь не нужно, если баланс просто меньше min_qty - это может быть штатно.

    else:
        trading_logger.error(f"Order Execution ({symbol}): Неизвестное действие '{action}'. Допустимы 'buy' или 'sell'.")
        return None

    return order_response # Возвращаем ответ от биржи




