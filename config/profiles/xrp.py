# --- Основные параметры ---
SYMBOL = 'XRPUSDT'             # Торговая пара
TIMEFRAME = '1m'               # Таймфрейм для свечей

# --- Использование индикаторов ---
USE_RSI = True      # использовать RSI при проверке
USE_MACD = True    # использовать MACD при проверке
USE_MACD_FOR_BUY = True  # использовать MACD для покупки
USE_MACD_FOR_SELL = True # использовать MACD для продажи
USE_EMA = False        # Использовать ли EMA в стратегии


# --- Настройки индикаторов ---
# RSI
RSI_PERIOD = 14                # Период RSI
RSI_OVERBOUGHT = 70            # RSI выше этого значения = перепроданность
RSI_OVERSOLD = 30              # RSI ниже этого значения = перепроданность

# MACD
MACD_FAST_PERIOD = 8           # Быстрый EMA для MACD
MACD_SLOW_PERIOD = 21          # Медленный EMA для MACD
MACD_SIGNAL_PERIOD = 9         # EMA сигнала для MACD

# EMA
EMA_PERIOD = 50

# --- Комиссия ---
COMMISSION_RATE = 0.001        # Комиссия биржи (0.1%)