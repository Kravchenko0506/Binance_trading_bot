import pytest
import json
import builtins
import os
from utils.profit_check import is_enough_profit
from services.binance_client import client

@pytest.fixture
def mock_ticker(monkeypatch):
    # Mock current market price to 1.05
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1.05"})

@pytest.fixture
def patch_open_with_file(monkeypatch):
    real_open = builtins.open

    def patch(symbol, json_data):
        os.makedirs("data", exist_ok=True)
        test_path = os.path.join("data", f"last_buy_price_{symbol}.json")
        with real_open(test_path, "w") as f:
            json.dump(json_data, f)

    return patch

def test_profit_check_returns_true_when_profit_high(patch_open_with_file, mock_ticker):
    # Buy price = 1.0, current price = 1.05 → profit = 5%
    patch_open_with_file("XRPUSDT", {"price": 1.0})
    assert is_enough_profit("XRPUSDT") is True

def test_profit_check_returns_false_when_profit_too_low(patch_open_with_file, monkeypatch):
    # Buy price = 1.0, current price = 1.001 → profit = 0.1%
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1.001"})
    patch_open_with_file("XRPUSDT", {"price": 1.0})
    assert is_enough_profit("XRPUSDT") is False

def test_stop_loss_triggered(monkeypatch):
    from utils.profit_check import is_stop_loss_triggered
    import builtins

    symbol = "XRPUSDT"
    os.makedirs("data", exist_ok=True)
    real_open = builtins.open

    # Записываем цену покупки 1.0
    with real_open(f"data/last_buy_price_{symbol}.json", "w") as f:
        json.dump({"price": 1.0}, f)

    # Текущая цена 0.95 → -5%
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "0.95"})

    assert is_stop_loss_triggered(symbol) is True

def test_stop_loss_not_triggered(monkeypatch):
    from utils.profit_check import is_stop_loss_triggered
    import builtins

    symbol = "XRPUSDT"
    os.makedirs("data", exist_ok=True)
    real_open = builtins.open

    with real_open(f"data/last_buy_price_{symbol}.json", "w") as f:
        json.dump({"price": 1.0}, f)

    # Текущая цена 0.99 → убыток 1%
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "0.99"})

    assert is_stop_loss_triggered(symbol) is False
    
def test_take_profit_reached(monkeypatch):
    from utils.profit_check import is_take_profit_reached
    import builtins

    symbol = "XRPUSDT"
    os.makedirs("data", exist_ok=True)
    real_open = builtins.open

    # Write buy price 1.0 to JSON
    with real_open(f"data/last_buy_price_{symbol}.json", "w") as f:
        json.dump({"price": 1.0}, f)

    # Current price = 1.06 → profit = 6%
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1.06"})

    # Expect True (take-profit triggered)
    assert is_take_profit_reached(symbol) is True

def test_take_profit_not_reached(monkeypatch):
    from utils.profit_check import is_take_profit_reached
    import builtins

    symbol = "XRPUSDT"
    os.makedirs("data", exist_ok=True)
    real_open = builtins.open

    # Write buy price 1.0 to JSON
    with real_open(f"data/last_buy_price_{symbol}.json", "w") as f:
        json.dump({"price": 1.0}, f)

    # Current price = 1.03 → profit = 3%
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1.03"})

    # Expect False (profit too low)
    assert is_take_profit_reached(symbol) is False

def test_take_profit_file_not_found(monkeypatch):
    from utils.profit_check import is_take_profit_reached

    symbol = "XRPUSDT"

    # Удаляем файл, если вдруг остался после предыдущих тестов
    file_path = f"data/last_buy_price_{symbol}.json"
    if os.path.exists(file_path):
        os.remove(file_path)

    # Мокаем текущую цену (любая)
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1000.0"})

    # Ожидаем False — файла нет
    assert is_take_profit_reached(symbol) is False
    
