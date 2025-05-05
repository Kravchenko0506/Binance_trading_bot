import json
import os
from services.binance_client import client
from config.settings import MIN_PROFIT_RATIO, STOP_LOSS_RATIO, TAKE_PROFIT_RATIO
from config import settings
from utils.quantity_utils import get_current_price
from utils.profit_check import load_last_buy_price
import logging

#Returns True if the current price is higher than the last purchase price by at least MIN_PROFIT_RATIO

from config import settings
from utils.quantity_utils import get_current_price
from utils.profit_check import load_last_buy_price
import logging
from utils.notifier import send_notification



# utils/profit_check.py

import json
import os
import logging
import asyncio

from config import settings
from utils.quantity_utils import get_current_price
from utils.notifier import send_notification

def get_last_buy_price_path(symbol: str) -> str:
    """Путь к файлу с ценой последней покупки."""
    return f"data/last_buy_price_{symbol}.json"

def save_last_buy_price(symbol: str, price: float):
    """Сохранить цену последней покупки в файл."""
    path = get_last_buy_price_path(symbol)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"price": price}, f)

def load_last_buy_price(symbol: str) -> dict:
    """Загрузить данные о цене последней покупки или вернуть пустой dict."""
    path = get_last_buy_price_path(symbol)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.warning(f"⚠️ Не удалось загрузить цену покупки для {symbol}: {e}")
        return {}

def is_enough_profit(symbol: str) -> bool:
    """
    Проверяет, достаточно ли прибыли, чтобы продавать:
      1) Загружает last_buy_price и текущую цену.
      2) Если нет данных — отменяет продажу.
      3) Вычисляет target = buy_price * (1 + MIN_PROFIT_RATIO).
      4) Если current_price < target — отменяет продажу.
    При отмене логгирует warning и шлёт уведомление в Telegram.
    """
    data = load_last_buy_price(symbol)
    buy_price = data.get("price") if data else None
    current_price = get_current_price(symbol)

    # 1) Проверка наличия данных
    if buy_price is None or current_price is None:
        msg = (
            f"⛔ Продажа отменена для {symbol}: "
            f"нет данных (buy_price={buy_price}, current_price={current_price})"
        )
        logging.warning(msg)
        # шлём в Telegram в фоне
        asyncio.create_task(send_notification(msg))
        return False

    # 2) Вычисляем целевой уровень продаж
    target_price = buy_price * (1 + settings.MIN_PROFIT_RATIO)
    if current_price < target_price:
        msg = (
            f"⛔ Продажа отменена для {symbol}: "
            f"куплено по {buy_price:.4f}, сейчас {current_price:.4f}, "
            f"нужно ≥ {target_price:.4f}"
        )
        logging.warning(msg)
        asyncio.create_task(send_notification(msg))
        return False

    # 3) Если всё ок — разрешаем продажу
    return True



# Returns True if current loss exceeds STOP_LOSS_RATIO

def is_stop_loss_triggered(symbol: str) -> bool:
    try:
        file_path = os.path.join("data", f"last_buy_price_{symbol}.json")
        with open(file_path, 'r') as f:
            data = json.load(f)
            last_buy_price = float(data['price'])
    except (FileNotFoundError, KeyError, ValueError):
        return False  # No data = no stop loss

    price_now = float(client.get_symbol_ticker(symbol=symbol)['price'])
    profit_ratio = (price_now - last_buy_price) / last_buy_price
    return profit_ratio < STOP_LOSS_RATIO

# True if current profit exceeds take-profit level

def is_take_profit_reached(symbol: str) -> bool:
    try:
        file_path = os.path.join("data", f"last_buy_price_{symbol}.json")
        with open(file_path, 'r') as f:
            data = json.load(f)
            last_buy_price = float(data['price'])
    except (FileNotFoundError, KeyError, ValueError):
        return False

    price_now = float(client.get_symbol_ticker(symbol=symbol)['price'])
    profit_ratio = (price_now - last_buy_price) / last_buy_price
    return profit_ratio >= TAKE_PROFIT_RATIO