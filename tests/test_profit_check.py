import pytest
import json
import builtins
from utils.profit_check import is_enough_profit
from services.binance_client import client

@pytest.fixture
def mock_ticker(monkeypatch):
    # Mock current market price to 1.05
    monkeypatch.setattr(client, "get_symbol_ticker", lambda **kwargs: {"price": "1.05"})

@pytest.fixture
def patch_open_with_file(tmp_path, monkeypatch):
    # Patch built-in open to use a fake file with JSON buy price
    real_open = builtins.open

    def patch(symbol, json_data):
        expected_path = tmp_path / f"last_buy_price_{symbol}.json"
        expected_path.write_text(json.dumps(json_data))

        def mocked_open(path, *args, **kwargs):
            if path == f"last_buy_price_{symbol}.json":
                return real_open(expected_path, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mocked_open)

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
