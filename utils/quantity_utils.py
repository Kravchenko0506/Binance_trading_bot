import math
from services.binance_client import client
import logging


def get_lot_size(symbol):
    try:
        exchange_info = client.get_symbol_info(symbol)
        for f in exchange_info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['stepSize']), float(f['minQty'])
    except Exception as e:
        logging.error(f"Ошибка при получении LOT_SIZE: {e}")
    return None, None


def round_step_size(quantity: float, step_size: float):
    factor = int(round(1.0 / step_size))
    return math.floor(quantity * factor) / factor
