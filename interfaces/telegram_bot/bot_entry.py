import asyncio
from aiogram.types import BotCommand

from interfaces.telegram_bot.bot_config import bot, dp
from interfaces.telegram_bot.handlers import router

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

# ▶️ Точка входа
if __name__ == "__main__":
    asyncio.run(start_aiogram_bot())

