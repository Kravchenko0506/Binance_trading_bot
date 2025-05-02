import json
import os
from services.binance_client import client
from config.settings import MIN_PROFIT_RATIO

def is_enough_profit(symbol: str) -> bool:
    try:
        file_path = os.path.join("data", f"last_buy_price_{symbol}.json")
        with open(file_path, 'r') as f:
            data = json.load(f)
            last_buy_price = float(data['price'])
    except (FileNotFoundError, KeyError, ValueError):
        return True # если цены нет — лучше продать, чем зависнуть
    
    price_now = float(client.get_symbol_ticker(symbol=symbol)['price'])
    profit_ratio = (price_now - last_buy_price) / last_buy_price
    return profit_ratio >= MIN_PROFIT_RATIO
