import os
from dotenv import load_dotenv

# Загружаем ключи API из .env файла
load_dotenv()

# --- Ключи Binance ---
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

# --- Торговля ---
LOG_FILE = 'trading_bot.log'
MIN_TRADE_AMOUNT = 5           # Минимальная сумма ордера (в USDT)
COMMISSION_RATE = 0.001        # Комиссия (0.1% = 0.001)
MIN_PROFIT_RATIO = 0.002
# --- Ограничения торгов ---
PRICE_PRECISION = 2            # Количество знаков после запятой для цены
MIN_ORDER_QUANTITY = 1         # Минимальное количество для ордера

