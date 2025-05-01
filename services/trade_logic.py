import logging
import numpy as np
from services.binance_client import client
from services.technical_indicators import calculate_rsi, calculate_macd, calculate_ema

def get_ohlcv(symbol, timeframe):
    try:
        klines = client.get_klines(symbol=symbol, interval=timeframe, limit=100)
        return np.array([float(kline[4]) for kline in klines])
    except Exception as e:
        logging.error(f"Ошибка при получении OHLCV: {e}")
        return np.array([])

def check_buy_sell_signals(profile):
    symbol             = profile.SYMBOL
    timeframe          = profile.TIMEFRAME
    rsi_period         = profile.RSI_PERIOD
    rsi_overbought     = profile.RSI_OVERBOUGHT
    rsi_oversold       = profile.RSI_OVERSOLD
    macd_fast_period   = profile.MACD_FAST_PERIOD
    macd_slow_period   = profile.MACD_SLOW_PERIOD
    macd_signal_period = profile.MACD_SIGNAL_PERIOD
    use_ema            = getattr(profile, "USE_EMA", False)
    ema_period         = getattr(profile, "EMA_PERIOD", 50)

    use_rsi            = getattr(profile, "USE_RSI", True)
    use_macd           = getattr(profile, "USE_MACD", True)
    use_macd_for_buy   = getattr(profile, "USE_MACD_FOR_BUY", False)
    use_macd_for_sell  = getattr(profile, "USE_MACD_FOR_SELL", False)
    

    prices = get_ohlcv(symbol, timeframe)
    if prices.size == 0:
        return 'hold'

    rsi = calculate_rsi(prices, rsi_period) if use_rsi else np.array([])
    macd, signal = calculate_macd(prices, macd_fast_period, macd_slow_period, macd_signal_period) if use_macd else (np.array([]), np.array([]))
    ema = calculate_ema(prices, ema_period) if use_ema else np.array([])
    if (use_rsi and rsi.size == 0) or (use_macd and (macd.size == 0 or signal.size == 0)) or (use_ema and ema.size == 0):
        return 'hold'

    last_rsi    = rsi[-1] if use_rsi else None
    last_macd   = macd[-1] if use_macd else None
    last_signal = signal[-1] if use_macd else None
    last_ema    = ema[-1] if use_ema else None
    last_price  = prices[-1]  

    buy = False
    if use_rsi:
        if use_macd and use_macd_for_buy:
            buy = last_rsi < rsi_oversold and last_macd > last_signal
        else:
            buy = last_rsi < rsi_oversold

    sell = False
    if use_rsi:
        if use_macd and use_macd_for_sell:
            sell = last_rsi > rsi_overbought and last_macd < last_signal
        else:
            sell = last_rsi > rsi_overbought
    
    if buy and use_ema and last_price < last_ema:
        buy = False  # отменяем покупку если цена ниже EMA

    if sell and use_ema and last_price > last_ema:
        sell = False  # отменяем продажу если цена выше EMA
        

    msg = ""
    if use_rsi and last_rsi is not None:
        msg += f"RSI: {last_rsi:.2f} "
    if use_macd and last_macd is not None:
        msg += f"MACD: {last_macd:.6f} "
    if use_ema and last_ema is not None:
        msg += f"EMA{ema_period}: {last_ema:.6f} "

    if buy:
        msg += "→ ПОКУПКА"
        logging.info(msg)
        print(msg)
        return 'buy'

    if sell:
        msg += "→ ПРОДАЖА"
        logging.info(msg)
        print(msg)
        return 'sell'

    # При hold
    msg += "→ нет сигнала"
    logging.info(msg)
    print(msg)
    return 'hold'