import numpy as np
import pytest
from services.trade_logic import check_buy_sell_signals

class DummyProfile:
    pass

@pytest.fixture
def buy_only_profile(monkeypatch):
    p = DummyProfile()
    p.SYMBOL = "TESTUSDT"
    p.TIMEFRAME = "1m"
    p.RSI_PERIOD = 14
    p.RSI_OVERBOUGHT = 70
    p.RSI_OVERSOLD = 30
    p.MACD_FAST_PERIOD = 12
    p.MACD_SLOW_PERIOD = 26
    p.MACD_SIGNAL_PERIOD = 9
    p.USE_RSI = True
    p.USE_MACD = False
    p.USE_EMA = False
    p.USE_MACD_FOR_BUY = False
    p.USE_MACD_FOR_SELL = False

    monkeypatch.setattr("services.trade_logic.get_ohlcv", lambda s, t: np.ones(100) * 100)
    monkeypatch.setattr("services.trade_logic.calculate_rsi", lambda prices, period: np.array([25]))
    monkeypatch.setattr("services.trade_logic.calculate_macd", lambda prices, f, s, sp: (np.array([0]), np.array([0])))
    monkeypatch.setattr("services.trade_logic.calculate_ema", lambda prices, period: np.array([100]))
    return p

@pytest.fixture
def buy_with_ema_profile(monkeypatch):
    p = DummyProfile()
    p.SYMBOL = "TESTUSDT"
    p.TIMEFRAME = "1m"
    p.RSI_PERIOD = 14
    p.RSI_OVERBOUGHT = 70
    p.RSI_OVERSOLD = 30
    p.MACD_FAST_PERIOD = 12
    p.MACD_SLOW_PERIOD = 26
    p.MACD_SIGNAL_PERIOD = 9
    p.USE_RSI = True
    p.USE_MACD = False
    p.USE_EMA = True
    p.EMA_PERIOD = 50
    p.USE_MACD_FOR_BUY = False
    p.USE_MACD_FOR_SELL = False

    monkeypatch.setattr("services.trade_logic.get_ohlcv", lambda s, t: np.linspace(50, 60, 100))
    monkeypatch.setattr("services.trade_logic.calculate_rsi", lambda prices, period: np.array([25]))
    monkeypatch.setattr("services.trade_logic.calculate_macd", lambda prices, f, s, sp: (np.array([0]), np.array([0])))
    monkeypatch.setattr("services.trade_logic.calculate_ema", lambda prices, period: np.full(prices.shape, 55))
    return p

def test_rsi_only_buy_signal(buy_only_profile):
    action = check_buy_sell_signals(buy_only_profile)
    assert action == 'buy'

def test_buy_signal_with_ema_filter(buy_with_ema_profile):
    action = check_buy_sell_signals(buy_with_ema_profile)
    assert action == 'buy'

