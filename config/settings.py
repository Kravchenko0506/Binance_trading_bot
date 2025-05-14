import os
import logging
from dotenv import load_dotenv

# Загружаем ключи API из .env файла
load_dotenv()

# --- Ключи Binance ---
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

# --- Торговля ---
LOG_FILE = 'trading.log'
MIN_TRADE_AMOUNT = 5           # Минимальная сумма ордера (в USDT)

USE_COMMISSION = True
COMMISSION_RATE = 0.001  

USE_MIN_PROFIT = True
MIN_PROFIT_RATIO = 0.002  

USE_STOP_LOSS = True
STOP_LOSS_RATIO = -0.02   

USE_TAKE_PROFIT = True
TAKE_PROFIT_RATIO = 0.05  
# --- Ограничения торгов ---
PRICE_PRECISION = 2            # Количество знаков после запятой для цены
MIN_ORDER_QUANTITY = 1         # Минимальное количество для ордера





