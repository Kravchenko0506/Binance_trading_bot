import math
import time
from services.binance_client import client
from utils.logger import trading_logger
from decimal import Decimal
from typing import Tuple, Optional

# Кеш exchange_info с автообновлением
exchange_info_cache = {
    "symbols": [],
    "last_update": 0
}
AUTO_REFRESH_INTERVAL = 6 * 60 * 60  # 6 часов

def get_lot_size(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Возвращает (step_size, min_qty) из фильтра 'LOT_SIZE' для заданного symbol.
    Использует кешированный exchange_info с автообновлением.
    """
    try:
        now = time.time()
        if not exchange_info_cache["symbols"] or (now - exchange_info_cache["last_update"]) > AUTO_REFRESH_INTERVAL:
            trading_logger.info("🔄 Загрузка exchange_info от Binance...")
            exchange_info = client.get_exchange_info()
            exchange_info_cache["symbols"] = exchange_info.get("symbols", [])
            exchange_info_cache["last_update"] = now
            trading_logger.info(f"✅ Кеш обновлён. Получено символов: {len(exchange_info_cache['symbols'])}")

        for s in exchange_info_cache["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step_size = float(f["stepSize"])
                        min_qty = float(f["minQty"])
                        return step_size, min_qty

        trading_logger.warning(f"LOT_SIZE фильтр не найден для {symbol}")

    except Exception as e:
        trading_logger.error(f"Ошибка при получении LOT_SIZE для {symbol}: {e}", exc_info=True)

    return None, None


def round_step_size(quantity: float, step_size: float):
    factor = int(round(Decimal("1.0") / Decimal(str(step_size))))
    return math.floor(quantity * factor) / factor

