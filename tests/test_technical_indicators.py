import numpy as np
from services.technical_indicators import calculate_rsi, calculate_macd, calculate_ema

def test_calculate_rsi_length_and_type():
    data = np.linspace(1, 100, num=100)
    rsi = calculate_rsi(data, timeperiod=14)
    assert isinstance(rsi, np.ndarray)
    assert rsi.shape[0] == data.shape[0]

def test_calculate_macd_length_and_type():
    data = np.linspace(1, 100, num=100)
    macd, signal = calculate_macd(data, fastperiod=12, slowperiod=26, signalperiod=9)
    assert isinstance(macd, np.ndarray) and isinstance(signal, np.ndarray)
    assert macd.shape == signal.shape == data.shape
    
def test_calculate_ema_length_and_type():
    data = np.linspace(1, 100, num=100)
    ema = calculate_ema(data, period=50)
    assert isinstance(ema, np.ndarray)
    assert ema.shape[0] == data.shape[0]    