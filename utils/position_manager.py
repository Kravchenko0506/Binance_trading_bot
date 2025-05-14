# utils/position_manager.py
import os
import json
from utils.logger import trading_logger, system_logger


def get_last_buy_price_path(symbol: str) -> str:
    """Возвращает путь к файлу с ценой последней покупки."""
    return f"data/last_buy_price_{symbol}.json"


def has_open_position(symbol: str) -> bool:
    """True, если есть сохранённая цена покупки (открыта позиция)."""
    return os.path.exists(get_last_buy_price_path(symbol))


def save_last_buy_price(symbol: str, price: float):
    """Сохраняет цену покупки в файл. Не сохраняет, если уже есть активная позиция."""
    path = get_last_buy_price_path(symbol)
    if os.path.exists(path):
        trading_logger.warning(f"save_last_buy_price: позиция по {symbol} уже существует. Повторная покупка отменена.")
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"price": price}, f)
        trading_logger.info(f"Цена покупки сохранена для {symbol}: {price}")
    except Exception as e:
        system_logger.error(f"Ошибка сохранения цены покупки для {symbol}: {e}", exc_info=True)


def load_last_buy_price(symbol: str) -> float | None:
    """Загружает цену покупки. Возвращает None, если нет позиции."""
    path = get_last_buy_price_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return float(data.get("price")) if "price" in data else None
    except Exception as e:
        system_logger.warning(f"Ошибка загрузки цены покупки для {symbol}: {e}", exc_info=True)
        return None


def clear_position(symbol: str):
    """Удаляет файл с позицией — вызывать после продажи. Игнорирует повторный вызов."""
    path = get_last_buy_price_path(symbol)
    try:
        if os.path.exists(path):
            os.remove(path)
            trading_logger.info(f"Файл позиции удалён для {symbol} (позиция закрыта)")
        else:
            trading_logger.debug(f"clear_position: позиция по {symbol} уже была закрыта ранее.")
    except Exception as e:
        system_logger.error(f"Ошибка удаления позиции для {symbol}: {e}", exc_info=True)
