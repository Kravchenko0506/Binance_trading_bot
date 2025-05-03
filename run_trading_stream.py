import sys
import argparse
import importlib
import asyncio
import datetime
import os
import logging

from services.binance_stream import listen_klines
from services.trade_logic import check_buy_sell_signals
from services.order_execution import place_order
from utils.logger import setup_logger
from services.technical_indicators import talib
from config.settings import log_enabled_features

setup_logger()

if talib is None:
    logging.warning("⚠️ TA-Lib is not installed. All indicators will use numpy fallbacks.")

PROFILES_DIR = 'config/profiles'

def list_available_profiles():
    return [f.replace('.py', '') for f in os.listdir(PROFILES_DIR)
            if f.endswith('.py') and f != '__init__.py']


async def price_processor(queue: asyncio.Queue, profile):
    while True:
        price = await queue.get()
        print(f"[WebSocket] New close price: {price}")
        action = check_buy_sell_signals(profile)
        if action != 'hold':
            place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)
        queue.task_done()

async def main(profile):

    print("\n🚀 Binance Trading Bot with WebSocket started!")
    print(f"✅ Profile loaded: {profile.SYMBOL}")
    print()
    log_enabled_features()
    print()
    start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"WebSocket bot started at {start_time} using profile {profile.SYMBOL}")
    print()
    action = check_buy_sell_signals(profile)
    if action != 'hold':
        place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)

    queue = asyncio.Queue()
    listener = asyncio.create_task(
        listen_klines(profile.SYMBOL, profile.TIMEFRAME, queue)
    )
    processor = asyncio.create_task(
        price_processor(queue, profile)
    )
    await asyncio.gather(listener, processor)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Binance trading stream")
    parser.add_argument("profile", nargs="?", help="Profile name from config/profiles")
    args = parser.parse_args()

    available_profiles = list_available_profiles()

    # Если профиль не передан — показать доступные и запросить ввод
    if not args.profile:
        print("\n📁 Available profiles:")
        for name in available_profiles:
            print(f" - {name}")
        profile_name = input("\nВведите профиль: ").strip().lower()
    else:
        profile_name = args.profile.strip().lower()

    if profile_name not in available_profiles:
        print(f"\n❌ Profile '{profile_name}' not found.\nAvailable: {', '.join(available_profiles)}")
        sys.exit(1)

    loaded_profile = importlib.import_module(f"config.profiles.{profile_name}")
    asyncio.run(main(loaded_profile))
  



