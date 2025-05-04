import sys
import argparse
import asyncio
import subprocess
from types import SimpleNamespace
from config.profile_loader import get_profile_by_name
from services.binance_stream import listen_klines
from services.trade_logic import check_buy_sell_signals
from services.order_execution import place_order
from utils.logger import setup_logger
from services.technical_indicators import talib
from config.settings import log_enabled_features
import pickle

async def price_processor(queue: asyncio.Queue, profile):
    while True:
        price = await queue.get()
        action = check_buy_sell_signals(profile)
        if action != 'hold':
            place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)
        queue.task_done()

async def trade_main(profile):
    setup_logger()
    if talib is None:
        print("⚠️ TA-Lib не установлен — используем numpy fallback")
    print(f"\n🚀 Торговля по профилю {profile.SYMBOL} начата!")
    log_enabled_features()
    action = check_buy_sell_signals(profile)
    if action != 'hold':
        place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)

    queue = asyncio.Queue()
    try:
        listener = asyncio.create_task(
            listen_klines(profile.SYMBOL, profile.TIMEFRAME, queue)
        )
        processor = asyncio.create_task(
            price_processor(queue, profile)
        )
        await asyncio.gather(listener, processor)
    except asyncio.CancelledError:
        print("❗️ Торговля остановлена по команде.")
        listener.cancel()
        processor.cancel()
        await asyncio.gather(listener, processor, return_exceptions=True)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        profile_dict = get_profile_by_name(sys.argv[1])
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
        asyncio.run(trade_main(profile))
    else:
        while True:
            print("\n🧠 Главное меню Binance-бота")
            print("1. Выбрать профиль")
            print("2. Менеджер профилей")
            print("3. Выход")
            choice = input("Выбери действие (1/2/3): ").strip()

            if choice == '1':
                from config.profile_loader import load_profiles
                profiles = load_profiles()
    
                if not profiles:
                    print("📭 Нет доступных профилей. Сначала создай хотя бы один через менеджер.")
                    continue

                print("\n📁 Доступные профили:")
                for name in profiles:
                    print(f" - {name}")

                profile_name = input("\nВведите имя профиля: ").strip().lower()
                if not profile_name:
                    print("❌ Имя профиля не может быть пустым.")
                    continue
                if profile_name not in profiles:
                    print(f"❌ Профиль '{profile_name}' не найден.")
                    continue

                try:
                    profile_dict = get_profile_by_name(profile_name)
                    profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})

                    print("\nЧто сделать с этим профилем?")
                    print("1. 🚀 Запустить торговлю")
                    print("2. 🧪 Запустить бэктест")
                    print("3. ↩️ Назад")
                    action = input("Выбор (1/2/3): ").strip()

                    if action == '1':
                        asyncio.run(trade_main(profile))
                    elif action == '2':
                        
                        with open("temp_profile.pkl", "wb") as f:
                            pickle.dump(profile, f)
                        subprocess.run(["python", "backtest.py", "--from-pkl"])
                    else:
                        print("↩️ Возврат в меню")
                except SystemExit:
                        continue

            
            elif choice == '2':
                subprocess.run(["python", "manage_profiles.py"])
            elif choice == '3':
                print("👋 Выход из программы.")
                break
            else:
                print("❌ Неверный выбор. Попробуй снова.")
                
# в самом низу run_trading_stream.py
async def trade_main_for_telegram(profile_name):
    from config.profile_loader import get_profile_by_name
    from types import SimpleNamespace

    profile_dict = get_profile_by_name(profile_name)
    profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})

    await trade_main(profile)
           





  



