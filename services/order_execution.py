import logging
import json
from services.binance_client import client
from utils.quantity_utils import get_lot_size, round_step_size
from config.settings import COMMISSION_RATE
from colorama import Fore, Style
from utils.profit_check import is_enough_profit



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
            # Save average buy price to JSON after market buy
            with open(f'last_buy_price_{symbol}.json', 'w') as f:
                json.dump({"price": avg_price}, f)

                total_commission = sum(float(f.get('commission', 0)) for f in fills)
                commission_asset = fills[0].get('commissionAsset', '') if fills else ''

                total_received = avg_price * total_qty

                log_message = (f"Покупка: {total_qty:.6f} {symbol.replace('USDT', '')} по средней цене {avg_price:.6f} USDT. "
                                f"Потрачено: {total_received:.6f} USDT. Комиссия: {total_commission:.6f} {commission_asset}.")



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
            # Проверка прибыли
            try:
                with open(f'last_buy_price_{symbol}.json', 'r') as f:
                    data = json.load(f)
                    last_buy_price = float(data['price'])
            except (FileNotFoundError, KeyError, ValueError):
                last_buy_price = None

            price_now = float(client.get_symbol_ticker(symbol=symbol)['price'])
            if last_buy_price:
                profit_ratio = (price_now - last_buy_price) / last_buy_price
                if not is_enough_profit(symbol):
                    logging.info("📉 Профит слишком мал — отмена продажи")
                    return

            # Выполняем продажу
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
        else:
            logging.warning(f"Недостаточно средств для продажи: {quantity} < {min_qty}")




