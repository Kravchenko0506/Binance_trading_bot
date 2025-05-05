# utils/profit_check.py

import json
import os
import logging
import asyncio

from services.binance_client import client
from config import settings
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
    # 1) Загрузка цен
    data = load_last_buy_price(symbol)
    buy_price = data.get("price") if data else None

    # берём текущую цену напрямую из Binance API
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker["price"])
    except Exception as e:
        logging.warning(f"⚠️ Не удалось получить текущую цену для {symbol}: {e}")
        current_price = None

    # 2) Проверка наличия данных
    if buy_price is None or current_price is None:
        msg = (
            f"⛔ Продажа отменена для {symbol}: "
            f"buy_price={buy_price}, current_price={current_price}"
        )
        logging.warning(msg)
        asyncio.create_task(send_notification(msg))
        return False

    # 3) Вычисляем цель
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

    # 4) Достаточно прибыли
    return True


def is_stop_loss_triggered(symbol: str) -> bool:
    """True, если убыток по текущей цене ниже STOP_LOSS_RATIO."""
    try:
        path = get_last_buy_price_path(symbol)
        with open(path, "r", encoding="utf-8") as f:
            last_buy_price = float(json.load(f)["price"])
    except Exception:
        return False

    price_now = float(client.get_symbol_ticker(symbol=symbol)["price"])
    return (price_now - last_buy_price) / last_buy_price < settings.STOP_LOSS_RATIO


def is_take_profit_reached(symbol: str) -> bool:
    """True, если прибыль по текущей цене выше TAKE_PROFIT_RATIO."""
    try:
        path = get_last_buy_price_path(symbol)
        with open(path, "r", encoding="utf-8") as f:
            last_buy_price = float(json.load(f)["price"])
    except Exception:
        return False

    price_now = float(client.get_symbol_ticker(symbol=symbol)["price"])
    return (price_now - last_buy_price) / last_buy_price >= settings.TAKE_PROFIT_RATIO
