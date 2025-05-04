import logging
import json
import os
from services.binance_client import client
from utils.quantity_utils import get_lot_size, round_step_size
import config.settings as settings
from colorama import Fore, Style
from utils.profit_check import is_enough_profit, is_stop_loss_triggered, is_take_profit_reached
import asyncio
from utils.notifier import send_notification



def get_balance(asset):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free'])

def place_order(action, symbol, commission_rate):
   
    step_size, min_qty = get_lot_size(symbol)

    if step_size is None:
        logging.error("Не удалось получить stepSize.")
        return

    if action == 'buy':
        usdt_balance = get_balance('USDT')
        price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        raw_quantity = (usdt_balance / price) * (1 - commission_rate)
        quantity = round_step_size(raw_quantity, step_size)

        if quantity >= min_qty:
            order = client.order_market_buy(symbol=symbol, quantity=quantity)
            fills = order.get('fills', [])
            total_qty = sum(float(f.get('qty', 0)) for f in fills)
            avg_price = sum(float(f.get('price', 0)) * float(f.get('qty', 0)) for f in fills) / total_qty if total_qty else 0
            # Save buy price to data/ folder
            os.makedirs("data", exist_ok=True)
            file_path = os.path.join("data", f"last_buy_price_{symbol}.json")
            with open(file_path, 'w') as f:
                json.dump({"price": avg_price}, f)


                total_commission = sum(float(f.get('commission', 0)) for f in fills)
                commission_asset = fills[0].get('commissionAsset', '') if fills else ''

                total_received = avg_price * total_qty

                log_message = (f"Покупка: {total_qty:.6f} {symbol.replace('USDT', '')} по средней цене {avg_price:.6f} USDT. "
                                f"Потрачено: {total_received:.6f} USDT. Комиссия: {total_commission:.6f} {commission_asset}.")



            logging.info(log_message)
            print(Fore.GREEN + log_message + Style.RESET_ALL)
           
        # ✅ Telegram-уведомление о покупке
            msg = (
                f"🟢 КУПЛЕНО\n"
                f"Символ: {symbol}\n"
                f"Объём: {total_qty:.6f}\n"
                f"Цена: {avg_price:.4f} USDT\n"
                f"Комиссия: {total_commission:.6f} {commission_asset}"
            )
            asyncio.create_task(send_notification(msg))
    

        else:
            logging.warning(f"Недостаточно средств для покупки: {quantity} < {min_qty}")

    elif action == 'sell':
        base_asset = symbol.replace('USDT', '')
        asset_balance = get_balance(base_asset)
        raw_quantity = asset_balance * (1 - commission_rate)
        quantity = round_step_size(raw_quantity, step_size)

        if quantity >= min_qty:
             # Forced sell if loss exceeds threshold
            if settings.USE_STOP_LOSS and is_stop_loss_triggered(symbol):

                logging.warning(f"❗ Stop-loss: убыток превышает {settings.STOP_LOSS_RATIO*100:.1f}% — принудительная продажа")
            else:
                if settings.USE_TAKE_PROFIT and is_take_profit_reached(symbol):

                    logging.info(f"✅ Take-profit: прибыль превышает {settings.TAKE_PROFIT_RATIO*100:.1f}% — фиксируем")
                else:
                    if settings.USE_MIN_PROFIT and not is_enough_profit(symbol):

                        logging.info("📉 Профит слишком мал — отмена продажи")
                        return

            # Making the sale
            order = client.order_market_sell(symbol=symbol, quantity=quantity)
            fills = order.get('fills', [])
            total_qty = sum(float(f.get('qty', 0)) for f in fills)
            avg_price = sum(float(f.get('price', 0)) * float(f.get('qty', 0)) for f in fills) / total_qty if total_qty else 0
            total_commission = sum(float(f.get('commission', 0)) for f in fills)
            commission_asset = fills[0].get('commissionAsset', '') if fills else ''
            total_received = avg_price * total_qty

            log_message = (f"Продажа: {total_qty:.6f} {base_asset} по средней цене {avg_price:.6f} USDT. "
                           f"Получено: {total_received:.6f} USDT. Комиссия: {total_commission:.6f} {commission_asset}.")
            logging.info(log_message)
            print(Fore.RED + log_message + Style.RESET_ALL)
            
            # ✅ Telegram-уведомление о продаже
            msg = (
                f"🔴 ПРОДАНО\n"
                f"Символ: {symbol}\n"
                f"Объём: {total_qty:.6f}\n"
                f"Цена: {avg_price:.4f} USDT\n"
                f"Комиссия: {total_commission:.6f} {commission_asset}"
            )
            asyncio.create_task(send_notification(msg))

            
        else:
            logging.warning(f"Недостаточно средств для продажи: {quantity} < {min_qty}")




