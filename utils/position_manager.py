# utils/position_manager.py
import os
import json
from utils.logger import trading_logger, system_logger
from services.binance_client import client


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
        trading_logger.warning(
            f"save_last_buy_price: позиция по {symbol} уже существует. Повторная покупка отменена.")
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"price": price}, f)
        trading_logger.info(f"Цена покупки сохранена для {symbol}: {price}")
    except Exception as e:
        system_logger.error(
            f"Ошибка сохранения цены покупки для {symbol}: {e}", exc_info=True)


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
        system_logger.warning(
            f"Ошибка загрузки цены покупки для {symbol}: {e}", exc_info=True)
        return None


def clear_position(symbol: str):
    """Удаляет файл с позицией — вызывать после продажи. Игнорирует повторный вызов."""
    path = get_last_buy_price_path(symbol)
    try:
        if os.path.exists(path):
            os.remove(path)
            trading_logger.info(
                f"Файл позиции удалён для {symbol} (позиция закрыта)")
        else:
            trading_logger.debug(
                f"clear_position: позиция по {symbol} уже была закрыта ранее.")
    except Exception as e:
        system_logger.error(
            f"Ошибка удаления позиции для {symbol}: {e}", exc_info=True)


def position_manager(profile):
    """
    Если на счету есть монета, но файл last_buy_price отсутствует — 
    сохраняет среднюю цену последней покупки и количество по всем трейдам последнего BUY-ордера.
    """
    symbol = profile.SYMBOL
    base_asset = symbol.replace('USDT', '')
    file_path = get_last_buy_price_path(symbol)

    if os.path.exists(file_path):
        trading_logger.info(
            f"position_manager: Позиция по {symbol} уже синхронизирована.")
        return

    try:
        # 1. Проверяем баланс base_asset
        balances = client.get_account().get('balances', [])
        balance = None
        for b in balances:
            if b['asset'] == base_asset:
                balance = float(b['free'])
                break
        if not balance or balance < 1e-8:
            trading_logger.info(
                f"position_manager: Баланс {base_asset} отсутствует или слишком мал.")
            return

        # 2. Получаем трейды (исполнения) только на покупку
        trades = client.get_my_trades(symbol=symbol)
        buy_trades = [t for t in trades if t.get('isBuyer')]
        if not buy_trades:
            trading_logger.warning(
                f"position_manager: Нет трейдов на покупку по {symbol}.")
            return

        # 3. Ищем orderId последней покупки
        last_order_id = buy_trades[-1]['orderId']
        # Собираем ВСЕ трейды, которые входят в этот orderId (с конца)
        last_order_trades = []
        for t in reversed(buy_trades):
            if t['orderId'] == last_order_id:
                last_order_trades.append(t)
            else:
                break
        last_order_trades.reverse()  # для порядка

        total_qty = 0
        total_cost = 0
        for t in last_order_trades:
            qty = float(t['qty'])
            price = float(t['price'])
            total_qty += qty
            total_cost += qty * price

        if total_qty == 0:
            trading_logger.warning(
                f"position_manager: Итоговое количество по последней покупке = 0.")
            return

        avg_price = total_cost / total_qty

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"price": avg_price, "quantity": total_qty}, f)
        trading_logger.info(
            f"🔄 Синхронизирована позиция по {symbol}: средняя цена {avg_price}, количество {total_qty}"
        )

    except Exception as e:
        system_logger.error(
            f"Ошибка sync_position_from_binance для {symbol}: {e}", exc_info=True)
