import logging
from services.binance_client import client
from utils.quantity_utils import get_lot_size, round_step_size
from config.settings import COMMISSION_RATE
from colorama import Fore, Style


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
            fills = order.get('fills', [{}])[0]
            price = float(fills.get('price', 0))
            qty = float(fills.get('qty', 0))
            commission = float(fills.get('commission', 0))
            commission_asset = fills.get('commissionAsset', '')

            total_spent = price * qty

            log_message = (f"Покупка: {qty} {symbol.replace('USDT', '')} по цене {price:.6f} USDT. "
                           f"Потрачено: {total_spent:.6f} USDT. Комиссия: {commission} {commission_asset}.")
            logging.info(log_message)
            print(Fore.GREEN + log_message + Style.RESET_ALL)

        else:
            logging.warning(f"Недостаточно средств для покупки: {quantity} < {min_qty}")

    elif action == 'sell':
        base_asset = symbol.replace('USDT', '')
        asset_balance = get_balance(base_asset)
        raw_quantity = asset_balance * (1 - commission_rate)
        quantity = round_step_size(raw_quantity, step_size)

        if quantity >= min_qty:
            order = client.order_market_sell(symbol=symbol, quantity=quantity)
            fills = order.get('fills', [{}])[0]
            price = float(fills.get('price', 0))
            qty = float(fills.get('qty', 0))
            commission = float(fills.get('commission', 0))
            commission_asset = fills.get('commissionAsset', '')

            total_received = price * qty

            log_message = (f"Продажа: {qty} {base_asset} по цене {price:.6f} USDT. "
                           f"Получено: {total_received:.6f} USDT. Комиссия: {commission} {commission_asset}.")
            logging.info(log_message)
            print(Fore.RED + log_message + Style.RESET_ALL)

        else:
            logging.warning(f"Недостаточно средств для продажи: {quantity} < {min_qty}")

    else:
        logging.warning(f"Неизвестное действие: {action}")





