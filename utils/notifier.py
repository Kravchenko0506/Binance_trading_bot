import json
import os
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = Bot(token=TELEGRAM_TOKEN)

def get_admin_id():
    try:
        with open("config/telegram_admins.json", "r", encoding="utf-8") as f:
            return json.load(f).get("admin_id")
    except Exception:
        return None

async def send_notification(text: str):
    chat_id = get_admin_id()
    if TELEGRAM_TOKEN and chat_id:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"❌ Ошибка при отправке уведомления: {e}")

