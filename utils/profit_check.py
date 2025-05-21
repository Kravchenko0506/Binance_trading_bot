# utils/profit_check.py

import json
import os
import asyncio

# Глобальные настройки, такие как MIN_PROFIT_RATIO, STOP_LOSS_RATIO и т.д.
from config import settings 
# Асинхронные уведомления
from utils.notifier import send_notification 
# Логгер для торговых операций
from utils.logger import trading_logger, system_logger 
from decimal import Decimal, getcontext


def get_last_buy_price_path(symbol: str) -> str:
    """
    Возвращает путь к файлу с ценой последней покупки для указанного символа.
    
    Args:
        symbol (str): Торговый символ, например, 'XRPUSDT'.

    Returns:
        str: Полный путь к файлу.
    """
    return f"data/last_buy_price_{symbol}.json"


def save_last_buy_price(symbol: str, price: float):
    """
    Сохраняет цену последней покупки для символа в JSON-файл.
    Создает директорию 'data', если она не существует.

    Args:
        symbol (str): Торговый символ.
        price (float): Цена покупки.
    """
    path = get_last_buy_price_path(symbol)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True) # Создаем директорию, если ее нет
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"price": price}, f)
        trading_logger.info(f"Profit Check ({symbol}): Цена последней покупки {price:.8f} сохранена в '{path}'.")
    except IOError as e:
        trading_logger.error(f"Profit Check ({symbol}): Ошибка записи файла цены покупки '{path}': {e}", exc_info=True)
        # ВАЖНО: Рассмотреть отправку критического уведомления, если цена не может быть сохранена
        asyncio.create_task(send_notification(f"🆘 КРИТИЧЕСКАЯ ОШИБКА: Не удалось сохранить цену покупки для {symbol}! Ручная проверка!"))
    except Exception as e:
        trading_logger.error(f"Profit Check ({symbol}): Непредвиденная ошибка при сохранении цены покупки '{path}': {e}", exc_info=True)
        asyncio.create_task(send_notification(f"🆘 КРИТИЧЕСКАЯ ОШИБКА: Непредвиденная ошибка при сохранении цены покупки для {symbol}!"))


def load_last_buy_price(symbol: str) -> float | None:
    """
    Загружает цену последней покупки из JSON-файла.

    Args:
        symbol (str): Торговый символ.

    Returns:
        float | None: Цена последней покупки или None, если не найдена или ошибка.
    """
    path = get_last_buy_price_path(symbol)
    if not os.path.exists(path):
        trading_logger.info(f"Profit Check ({symbol}): Файл с ценой покупки '{path}' не найден (вероятно, активной позиции нет).")
        return None 
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            price = data.get("price")
            if price is None or not isinstance(price, (float, int)):
                trading_logger.error(f"Profit Check ({symbol}): Некорректный формат данных в файле '{path}'. Ключ 'price' отсутствует или не является числом. Данные: {data}")
                return None
            # trading_logger.debug(f"Profit Check ({symbol}): Загружена цена покупки {float(price):.8f} из '{path}'.")
            return float(price)
    except json.JSONDecodeError as e:
        trading_logger.error(f"Profit Check ({symbol}): Ошибка декодирования JSON из файла '{path}': {e}. Содержимое могло быть повреждено.")
        return None
    except Exception as e: 
        trading_logger.error(f"Profit Check ({symbol}): Не удалось загрузить цену покупки из '{path}': {e}", exc_info=True)
        return None


def is_enough_profit(symbol: str, current_price: float, last_buy_price: float | None, context: str = "") -> bool:
    """
    Проверяет, достигнут ли минимальный профит.

    Args:
        symbol (str): Торговая пара.
        current_price (float): Текущая цена.
        last_buy_price (float | None): Цена покупки.
        context (str): Источник вызова ("risk" или "strategy").

    Returns:
        bool: True, если минимальный профит достигнут.
    """
    if not getattr(settings, 'USE_MIN_PROFIT', False):
        return False

    if last_buy_price is None or last_buy_price <= 0:
        if context != "strategy":
            trading_logger.debug(f"[MinProfit] {symbol}: Нет last_buy_price — считаем профит допустимым.")
        return True

    min_profit_ratio = getattr(settings, 'MIN_PROFIT_RATIO', 0.01)
    target_price = last_buy_price * (1 + min_profit_ratio)
    price_change_ratio = (current_price - last_buy_price) / last_buy_price
    profit_pct = price_change_ratio * 100

    if current_price >= target_price:
        if context != "strategy":
            trading_logger.info(
                f"✅ Минимальный профит ДОСТИГНУТ для {symbol}. "
                f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}, Цель: {target_price:.8f}. "
                f"Профит: {profit_pct:.2f}%, Порог: {min_profit_ratio*100:.2f}%"
            )
        return True
    else:
        if context != "strategy":
            trading_logger.info(
                f"❌ Минимальный профит НЕ достигнут для {symbol}. "
                f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}, Цель: {target_price:.8f}. "
                f"Профит: {profit_pct:.2f}%, Порог: {min_profit_ratio*100:.2f}%"
            )
        return False
    
def is_stop_loss_triggered(symbol: str, current_price: float, last_buy_price: float | None) -> bool:
    """
    Проверяет, сработал ли стоп-лосс на основе STOP_LOSS_RATIO.

    Args:
        symbol (str): Торговый символ.
        current_price (float): Текущая рыночная цена актива.
        last_buy_price (float | None): Цена последней покупки. Если None, стоп-лосс не может сработать.

    Returns:
        bool: True, если убыток достиг или превысил порог стоп-лосса, иначе False.
    """
    if not getattr(settings, 'USE_STOP_LOSS', False): # Проверяем флаг из настроек
        return False

    if last_buy_price is None or last_buy_price <= 0:
        trading_logger.debug(f"Stop-Loss Check ({symbol}): Проверка невозможна - нет корректной цены покупки (цена: {last_buy_price}).")
        return False

    stop_loss_ratio = getattr(settings, 'STOP_LOSS_RATIO', -0.02) # Ожидается отрицательное значение

    # Рассчитываем процент изменения цены
    # (цена_продажи - цена_покупки) / цена_покупки
    price_change_ratio = (current_price - last_buy_price) / last_buy_price
    
    # Стоп-лосс срабатывает, если изменение цены МЕНЬШЕ, чем установленный stop_loss_ratio
    # Например, если stop_loss_ratio = -0.02 (-2%), а price_change_ratio = -0.03 (-3%), то условие True
    triggered = price_change_ratio < stop_loss_ratio
    
    if triggered:
        trading_logger.warning(
            f"‼️ Stop-Loss TRIGGERED for {symbol}! "
            f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}. "
            f"Изменение цены: {price_change_ratio*100:.2f}%, Порог SL: {stop_loss_ratio*100:.2f}%"
        )
    else:
        trading_logger.debug(
            f"Stop-Loss Check ({symbol}): Not triggered. "
            f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}. "
            f"Изменение цены: {price_change_ratio*100:.2f}%, Порог SL: {stop_loss_ratio*100:.2f}%"
        )
    return triggered


def is_take_profit_reached(symbol: str, current_price: float, last_buy_price: float | None) -> bool:
    """
    Проверяет, достигнут ли тейк-профит на основе TAKE_PROFIT_RATIO.

    Args:
        symbol (str): Торговый символ.
        current_price (float): Текущая рыночная цена актива.
        last_buy_price (float | None): Цена последней покупки. Если None, тейк-профит не может быть достигнут.

    Returns:
        bool: True, если прибыль достигла или превысила порог тейк-профита, иначе False.
    """
    if not getattr(settings, 'USE_TAKE_PROFIT', False):
        return False

    if last_buy_price is None or last_buy_price <= 0:
        trading_logger.debug(f"Take-Profit Check ({symbol}): Проверка невозможна — нет корректной цены покупки (цена: {last_buy_price}).")
        return False

    take_profit_ratio = getattr(settings, 'TAKE_PROFIT_RATIO', 0.05)
    target_price = last_buy_price * (1 + take_profit_ratio)
    price_change_ratio = (current_price - last_buy_price) / last_buy_price
    profit_pct = price_change_ratio * 100

    if current_price >= target_price:
        trading_logger.info(
            f"✅ Take-Profit REACHED for {symbol}! "
            f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}, Цель: {target_price:.8f}. "
            f"Профит: {profit_pct:.2f}%, Порог TP: {take_profit_ratio*100:.2f}%"
        )
        return True
    else:
        trading_logger.debug(
            f"Take-Profit Check ({symbol}): НЕ достигнут. "
            f"Куплено: {last_buy_price:.8f}, Текущая: {current_price:.8f}, Цель: {target_price:.8f}. "
            f"Профит: {profit_pct:.2f}%, Порог TP: {take_profit_ratio*100:.2f}%"
        )
        return False    

