import logging
import numpy as np
import pytest

from services import technical_indicators as ti

@pytest.fixture
def no_talib(monkeypatch):
    # Выключаем talib
    monkeypatch.setattr(ti, "talib", None)
    monkeypatch.setattr(ti, "calculate_rsi", ti.calculate_rsi)
    monkeypatch.setattr(ti, "calculate_macd", ti.calculate_macd)
    monkeypatch.setattr(ti, "calculate_ema", ti.calculate_ema)

def test_rsi_fallback_log(no_talib, caplog):
    caplog.set_level(logging.WARNING)
    data = np.linspace(50, 100, 100)
    ti.calculate_rsi(data, 14)
    assert "fallback RSI" in caplog.text


def test_macd_fallback_log(no_talib, caplog):
    caplog.set_level(logging.WARNING)
    data = np.linspace(50, 100, 100)
    ti.calculate_macd(data, 6, 13, 5)
    assert "fallback MACD" in caplog.text

def test_ema_fallback_log(no_talib, caplog):
    caplog.set_level(logging.WARNING)
    data = np.linspace(50, 100, 100)
    ti.calculate_ema(data, 50)
    assert "fallback EMA" in caplog.text
