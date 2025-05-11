import asyncio
from aiogram.types import BotCommand

from interfaces.telegram_bot.bot_config import bot, dp
from interfaces.telegram_bot.handlers import router
from services.binance_stream import stop_websocket
import signal

# ✅ Задаём системное меню Telegram
async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="menu", description="Восстановить клавиатуру"),
    ]
    await bot.set_my_commands(commands)

# 🔁 Основной запуск
async def start_aiogram_bot():
    dp.include_router(router)
    await set_bot_commands()         # 🆕 меню команд
    await dp.start_polling(bot)


def stop_bot_gracefully(*args):
    """Обработчик сигнала SIGINT для остановки бота и WebSocket"""
    # тут можно отменить ещё другие async задачи, если нужно
    print("🛑 Остановка по сигналу пользователя")
    stop_websocket()
   
# ▶ Точка входа
if __name__ == "__main__":
    
    signal.signal(signal.SIGINT, stop_bot_gracefully)
    signal.signal(signal.SIGTERM, stop_bot_gracefully)

    asyncio.run(start_aiogram_bot())

