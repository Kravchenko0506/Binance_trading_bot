try:
    import talib
except ImportError:
    talib = None
    print("❌ TA-Lib not available. Using fallback.")
import numpy as np
import logging

def calculate_rsi(data, timeperiod):
    try:
        if talib:
            return talib.RSI(data, timeperiod=timeperiod)
        else:
            logging.warning("📉 TA-Lib not available. Using fallback RSI.")
        return fallback_rsi(data, timeperiod)

    except Exception as e:
        logging.error(f"Ошибка при расчете RSI: {e}")
        return np.array([])

def calculate_macd(data, fastperiod, slowperiod, signalperiod):
    try:
        if talib:
            macd, signal, _ = talib.MACD(data, fastperiod, slowperiod, signalperiod)
            return macd, signal
        else:
            logging.warning("📉 TA-Lib not available. Using fallback MACD.")
            return fallback_macd(data, fastperiod, slowperiod, signalperiod)
    except Exception as e:
        logging.error(f"Ошибка при расчете MACD: {e}")
        return np.array([]), np.array([])

def calculate_ema(data, period):
    try:
        if talib:
            return talib.EMA(data, timeperiod=period)
        else:
            logging.warning("📉 TA-Lib not available. Using fallback EMA.")
            return fallback_ema(data, period)

    except Exception as e:
        logging.error(f"Ошибка при расчете EMA: {e}")
        return np.array([])

    
def fallback_ema(data, period):
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    ema = np.convolve(data, weights, mode='full')[:len(data)]
    return np.concatenate([np.full(period - 1, ema[period - 1]), ema[period - 1:]])

def fallback_rsi(data, period):
    delta = np.diff(data)
    up = delta.clip(min=0)
    down = -delta.clip(max=0)

    roll_up = np.convolve(up, np.ones(period), 'valid') / period
    roll_down = np.convolve(down, np.ones(period), 'valid') / period

    rs = roll_up / (roll_down + 1e-9)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return np.concatenate([np.full(period, np.nan), rsi])
def fallback_macd(data, fast=12, slow=26, signal=9):
    ema_fast = fallback_ema(data, fast)
    ema_slow = fallback_ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = fallback_ema(macd_line, signal)
    return macd_line, signal_line

    
