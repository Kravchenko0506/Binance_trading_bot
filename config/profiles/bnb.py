# --- Основные параметры ---
SYMBOL = 'BNBUSDT'             # Торговая пара
TIMEFRAME = '5m'               # Таймфрейм для свечей

# --- Использование индикаторов ---
USE_RSI = True      # использовать RSI при проверке
USE_MACD = False    # использовать MACD при проверке
USE_MACD_FOR_BUY = True  # использовать MACD для покупки
USE_MACD_FOR_SELL = True # использовать MACD для продажи
USE_EMA = False        # Использовать ли EMA в стратегии

# --- Настройки индикаторов ---
# RSI
RSI_PERIOD = 14                # Период RSI
RSI_OVERBOUGHT = 70            # RSI выше этого значения = перепроданность
RSI_OVERSOLD = 40              # RSI ниже этого значения = перепроданность

# MACD
MACD_FAST_PERIOD = 6           # Быстрый EMA для MACD
MACD_SLOW_PERIOD = 13          # Медленный EMA для MACD
MACD_SIGNAL_PERIOD = 5         # EMA сигнала для MACD
# EMA
EMA_PERIOD = 50

# --- Комиссия ---
COMMISSION_RATE = 0.001        # Комиссия биржи (0.1%)