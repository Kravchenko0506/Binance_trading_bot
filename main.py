import asyncio
import sys
import os
import importlib
import logging
import datetime
from config.settings import API_KEY, API_SECRET, LOG_FILE, MIN_TRADE_AMOUNT, COMMISSION_RATE, PRICE_PRECISION, MIN_ORDER_QUANTITY
from services.trade_logic import check_buy_sell_signals
from services.order_execution import place_order
from utils.logger import setup_logger

setup_logger()


# Сканируем доступные профили
profiles_dir = 'config/profiles'
AVAILABLE_PROFILES = [f.replace('.py', '') for f in os.listdir(profiles_dir) if f.endswith('.py') and f != '__init__.py']

# Если профиль не передан в аргументах, спросить у пользователя
if len(sys.argv) < 2:
    print("\n🚀 Добро пожаловать в Binance Trading Bot!")
    print("\nДоступные профили для торговли:")
    for profile in AVAILABLE_PROFILES:
        print(f" - {profile}")
    print("\nВведите название профиля для торговли (например: xrp):")
    profile_name = input("Профиль: ").lower()
else:
    profile_name = sys.argv[1].lower()

# Проверка, существует ли выбранный профиль
if profile_name not in AVAILABLE_PROFILES:
    print(f"\n❌ Ошибка: Профиль '{profile_name}' не найден.\nДоступные профили: {', '.join(AVAILABLE_PROFILES)}")
    sys.exit(1)

# Логируем выбранный профиль
logging.info(f"Выбран профиль для торговли: {profile_name.upper()}")

# Динамически импортируем профиль
try:
    profile = importlib.import_module(f"config.profiles.{profile_name}")
except ModuleNotFoundError:
    print(f"Ошибка: Профиль '{profile_name}' не найден в папке config/profiles/")
    sys.exit(1)

# Теперь все переменные доступны через profile
SYMBOL = profile.SYMBOL
TIMEFRAME = profile.TIMEFRAME
USE_RSI = profile.USE_RSI
USE_MACD = profile.USE_MACD
USE_MACD_FOR_BUY = profile.USE_MACD_FOR_BUY
USE_MACD_FOR_SELL = profile.USE_MACD_FOR_SELL
RSI_PERIOD = profile.RSI_PERIOD
RSI_OVERBOUGHT = profile.RSI_OVERBOUGHT
RSI_OVERSOLD = profile.RSI_OVERSOLD
MACD_FAST_PERIOD = profile.MACD_FAST_PERIOD
MACD_SLOW_PERIOD = profile.MACD_SLOW_PERIOD
MACD_SIGNAL_PERIOD = profile.MACD_SIGNAL_PERIOD
COMMISSION_RATE = profile.COMMISSION_RATE

# Выводим инфу
print(f"\n✅ Запущена торговля по профилю: {profile_name.upper()} - Пара: {SYMBOL}")
logging.info(f"Торговля началась по паре: {SYMBOL}")

# Логируем время запуска
start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
logging.info(f"Бот запущен в {start_time}  профилем {profile_name.upper()} для пары {SYMBOL}")

# Основная логика бота
async def main():
    
    # Переходим в цикл с паузой после каждой проверки
    print(f"\n⏳ Бот работает. Проверка сигналов каждые 60 секунд...")
    while True:
        action = await asyncio.to_thread(check_buy_sell_signals, profile)
        if action != 'hold':
            await asyncio.to_thread(place_order, action, SYMBOL, COMMISSION_RATE)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

    
