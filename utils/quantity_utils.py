import math
from services.binance_client import client
from utils.logger import trading_logger
from decimal import Decimal
from typing import Tuple, Optional


def get_lot_size(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Возвращает (step_size, min_qty) из фильтра 'LOT_SIZE' для заданного symbol.

    :param symbol: Символ торговой пары (например 'XRPUSDT')
    :return: Кортеж из двух значений:
             - step_size: минимальный шаг изменения количества
             - min_qty: минимальное допустимое количество для ордера
             Если фильтр не найден — вернёт (None, None)
    """
    try:
        exchange_info = client.get_symbol_info(symbol)
        for f in exchange_info.get('filters', []):
            if f.get('filterType') == 'LOT_SIZE':
                step_size = float(f['stepSize'])
                min_qty = float(f['minQty'])
                return step_size, min_qty
        trading_logger.warning(f"LOT_SIZE фильтр не найден для {symbol}")
    except Exception as e:
        trading_logger.error(f"Ошибка при получении LOT_SIZE для {symbol}: {e}", exc_info=True)
    return None, None


def round_step_size(quantity: float, step_size: float):
    factor = int(round(Decimal("1.0") / step_size))
    return math.floor(quantity * factor) / factor
