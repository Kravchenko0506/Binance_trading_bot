import sys
import asyncio
import subprocess
import os
import pickle
import logging
from types import SimpleNamespace
from config.profile_loader import get_profile_by_name
from services.binance_stream import listen_klines, stop_websocket
from services.trade_logic import check_buy_sell_signals
from services.order_execution import place_order
from utils.logger import setup_logger
from services.technical_indicators import talib
from config.settings import log_enabled_features

# === Настройка системного логгера ===
os.makedirs("logs", exist_ok=True)
system_logger = logging.getLogger("system")
system_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler("logs/system.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
system_logger.addHandler(file_handler)


async def price_processor(queue: asyncio.Queue, profile):
    try:
        while True:
            price = await queue.get()
            action = check_buy_sell_signals(profile)
            if action != 'hold':
                place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)
            queue.task_done()
    except asyncio.CancelledError:
        system_logger.info("📉 Задача price_processor отменена (CancelledError)")
    except Exception as e:
        system_logger.exception(f"❌ Ошибка в price_processor: {e}")


async def trade_main(profile):
    setup_logger()
    system_logger.info(f"🚀 Торговля по профилю {profile.SYMBOL} запущена")

    if talib is None:
        system_logger.warning("⚠️ TA-Lib не установлен — используем fallback")

    log_enabled_features()

    queue = asyncio.Queue()
    listener = asyncio.create_task(listen_klines(profile.SYMBOL, profile.TIMEFRAME, queue))
    processor = asyncio.create_task(price_processor(queue, profile))

    try:
        await asyncio.gather(listener, processor)
    except asyncio.CancelledError:
        system_logger.info("🛑 Торговля отменена пользователем или системой (CancelledError)")
        listener.cancel()
        processor.cancel()
        await asyncio.gather(listener, processor, return_exceptions=True)
    except Exception as e:
        system_logger.exception(f"❗ Необработанная ошибка в trade_main: {e}")
    finally:
        stop_websocket()
        system_logger.info("📡 WebSocket остановлен (stop_websocket)")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        try:
            profile_dict = get_profile_by_name(sys.argv[1])
            profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
            asyncio.run(trade_main(profile))
            system_logger.info("✅ Торговля завершена корректно")
        except Exception as e:
            system_logger.exception(f"❗ Ошибка на верхнем уровне: {e}")
    else:
        print("❌ Укажи имя профиля как аргумент.")
        
async def trade_main_for_telegram(profile_name: str):
    """
    Используется из Telegram-бота: запускает торговлю по имени профиля
    """
    try:
        profile_dict = get_profile_by_name(profile_name)
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
        await trade_main(profile)
    except Exception as e:
        system_logger.exception(f"❌ Ошибка при запуске торговли из Telegram: {e}")







  



