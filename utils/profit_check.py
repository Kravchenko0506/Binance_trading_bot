# utils/profit_check.py

import json
import os
import asyncio # Нужен для asyncio.create_task

# Убираем client.get_symbol_ticker() из этих функций
# from services.binance_client import client # Этот импорт здесь больше не нужен для этих функций
from config import settings # Предполагаем, что settings содержит MIN_PROFIT_RATIO, STOP_LOSS_RATIO, TAKE_PROFIT_RATIO
from utils.notifier import send_notification
from utils.logger import trading_logger, system_logger # Добавим system_logger для некоторых ошибок
from utils.position_manager import load_last_buy_price


# --- ИСПРАВЛЕННЫЕ ФУНКЦИИ ---
def is_enough_profit(symbol: str, current_price: float) -> bool:
    """
    Проверяет, достаточно ли прибыли для продажи, используя переданную current_price.
    """
    buy_price = load_last_buy_price(symbol)

    if buy_price is None: # Если нет цены покупки, не можем рассчитать профит
        # Это не обязательно ошибка, возможно, еще не было покупки
        # trading_logger.debug(f"is_enough_profit ({symbol}): Цена покупки не найдена, профит не проверяется.")
        return False # Или True, в зависимости от твоей логики (если нет покупки, то "достаточно прибыли" для продажи?)
                      # Обычно False, если нет открытой позиции.

    # current_price уже передана, API-запрос не нужен
    # try:
    #     ticker = client.get_symbol_ticker(symbol=symbol) # УДАЛЕНО
    #     current_price_from_api = float(ticker["price"]) # УДАЛЕНО
    # except Exception as e:
    #     trading_logger.warning(f"⚠️ is_enough_profit: Не удалось получить текущую цену для {symbol}: {e}")
    #     return False # Ошибка получения цены, считаем, что профит недостаточен

    # Проверка наличия current_price (на всякий случай, если передали None)
    if current_price is None:
        trading_logger.warning(f"is_enough_profit ({symbol}): current_price не передана.")
        return False

    target_price = buy_price * (1 + settings.MIN_PROFIT_RATIO)
    if current_price < target_price:
        msg = (
            f"⛔ Продажа по мин. профиту отменена для {symbol}: "
            f"куплено по {buy_price:.4f}, сейчас {current_price:.4f}, "
            f"нужно >= {target_price:.4f} (мин. профит {settings.MIN_PROFIT_RATIO*100:.2f}%)"
        )
        trading_logger.info(msg) # Можно INFO, так как это штатная проверка
        # asyncio.create_task(send_notification(msg)) # Уведомление об отмене продажи по мин. профиту может быть избыточным
        return False

    # trading_logger.info(f"is_enough_profit ({symbol}): Достаточно прибыли для продажи. Цена: {current_price}, Цель: {target_price}")
    return True


def is_stop_loss_triggered(symbol: str, current_price: float) -> bool: # <--- Добавлен current_price
    """True, если убыток по переданной current_price ниже STOP_LOSS_RATIO."""
    buy_price = load_last_buy_price(symbol)
    if buy_price is None:
        return False # Нет цены покупки, нечему срабатывать

    # price_now = float(client.get_symbol_ticker(symbol=symbol)["price"]) # УДАЛЕНО
    price_now = current_price # Используем переданную цену

    if buy_price == 0: return False # Избегаем деления на ноль
    
    triggered = (price_now - buy_price) / buy_price < settings.STOP_LOSS_RATIO # STOP_LOSS_RATIO обычно отрицательный
    # if triggered:
    #     trading_logger.warning(f"is_stop_loss_triggered ({symbol}): Сработал стоп-лосс. Цена покупки: {buy_price}, Цена сейчас: {price_now}, Лимит: {settings.STOP_LOSS_RATIO*100:.2f}%")
    return triggered


def is_take_profit_reached(symbol: str, current_price: float) -> bool: # <--- Добавлен current_price
    """True, если прибыль по переданной current_price выше TAKE_PROFIT_RATIO."""
    buy_price = load_last_buy_price(symbol)
    if buy_price is None:
        return False

    # price_now = float(client.get_symbol_ticker(symbol=symbol)["price"]) # УДАЛЕНО
    price_now = current_price # Используем переданную цену

    if buy_price == 0: return False
    
    reached = (price_now - buy_price) / buy_price >= settings.TAKE_PROFIT_RATIO
    # if reached:
    #     trading_logger.info(f"is_take_profit_reached ({symbol}): Достигнут тейк-профит. Цена покупки: {buy_price}, Цена сейчас: {price_now}, Цель: {settings.TAKE_PROFIT_RATIO*100:.2f}%")
    return reached