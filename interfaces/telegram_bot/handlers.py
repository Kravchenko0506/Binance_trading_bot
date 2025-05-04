from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import os, json

from bot_control.control_center import get_status, start_trading, stop_trading
from run_trading_stream import trade_main_for_telegram
from config.profile_loader import get_all_profiles

router = Router()

# ───── ВРЕМЕННЫЕ СОСТОЯНИЯ ─────────────────────────────────────
AUTH_FILE = "config/auth.json"
PENDING_AUTH = set()  # кто ждёт ввода пароля
USER_MESSAGES = {}    # user_id → [msg_id,...] для очистки

# ───── ФУНКЦИИ АВТОРИЗАЦИИ ─────────────────────────────────────

def load_auth_data() -> dict:
    """Загружает auth.json или создаёт с нуля"""
    if not os.path.exists(AUTH_FILE):
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        data = {"passwords": {}, "users": {}}
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data
    with open(AUTH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_auth_data(data: dict):
    """Сохраняет auth.json"""
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def is_authenticated(user_id: int) -> bool:
    """Проверка: есть ли user_id в списке users"""
    return str(user_id) in load_auth_data().get("users", {})

def verify_password(password: str) -> str | None:
    """Сверяет пароль → возвращает API-ключ"""
    return load_auth_data().get("passwords", {}).get(password)

def register_user(user_id: int, api_key: str):
    """Регистрирует Telegram ID → API ключ"""
    data = load_auth_data()
    data.setdefault("users", {})[str(user_id)] = api_key
    save_auth_data(data)

# ───── УТИЛИТА: отправка и удаление старых сообщений ────────────

async def send_clean(bot: Bot, user_id: int, text: str, **kwargs):
    # Удалить ВСЕ старые сообщения пользователя, если есть
    for msg_id in USER_MESSAGES.get(user_id, []):
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception as e:
            print(f"[×] Не удалось удалить сообщение {msg_id}: {e}")
    USER_MESSAGES[user_id] = []

    # Отправить новое сообщение и сохранить ID
    msg = await bot.send_message(chat_id=user_id, text=text, **kwargs)
    USER_MESSAGES.setdefault(user_id, []).append(msg.message_id)


# ───── ГЕНЕРАЦИЯ МЕНЮ ───────────────────────────────────────────

def generate_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Меню: динамически показывает регистрацию или команды"""
    auth = is_authenticated(user_id)
    kb = [
        [KeyboardButton(text="▶️ Запустить"), KeyboardButton(text="⏹ Остановить")],
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📤 Лог")]
    ]
    if not auth:
        kb.append([KeyboardButton(text="🔐 Зарегистрироваться")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ───── ОБРАБОТЧИКИ КОМАНД ───────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    """Команда /start: показывает меню"""
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        await message.answer("👋 Привет! Чтобы получить доступ, отправь /login")
        return
    await send_clean(bot, user_id,
        "✅ Добро пожаловать! Вы авторизованы.\nВыберите действие:",
        reply_markup=generate_main_menu(user_id)
    )

@router.message(Command("menu"))
async def cmd_menu(message: types.Message, bot: Bot):
    """Команда /menu: принудительно перерисовать меню"""
    user_id = message.from_user.id
    if not is_authenticated(user_id):
        await message.answer("⛔️ Вы не авторизованы. /login")
        return
    await send_clean(bot, user_id, "📋 Главное меню:", reply_markup=generate_main_menu(user_id))

@router.message(Command("login"))
async def cmd_login(message: types.Message):
    """Команда /login: запрашивает пароль"""
    u = message.from_user.id
    if is_authenticated(u):
        await message.answer("✅ Вы уже авторизованы. /start для меню")
        return
    PENDING_AUTH.add(u)
    await message.answer("🔒 Введите пароль:")

@router.message(lambda m: m.from_user.id in PENDING_AUTH)
async def process_password(message: types.Message):
    """Обрабатывает пароль, если пользователь ожидается"""
    u = message.from_user.id
    PENDING_AUTH.remove(u)
    api_key = verify_password(message.text.strip())
    if api_key:
        register_user(u, api_key)
        await message.answer(
            "🎉 Пароль верный! Добро пожаловать.",
            reply_markup=generate_main_menu(u)
        )
    else:
        await message.answer("❌ Неверный пароль. Попробуйте снова: /login")

# ───── ОСНОВНОЕ МЕНЮ ────────────────────────────────────────────

@router.message(lambda m: m.text == "📊 Статус")
async def show_status(message: types.Message):
    """Показывает текущий статус торговли"""
    if not is_authenticated(message.from_user.id):
        await message.answer("⛔️ Не авторизованы. /login")
        return
    st = get_status()
    await message.answer(
        f"⚙️ Статус: {'✅ работает' if st['running'] else '⛔️ остановлен'}\n"
        f"Профиль: {st['profile'] or 'не выбран'}"
    )

@router.message(lambda m: m.text == "▶️ Запустить")
async def cmd_run(message: types.Message, bot: Bot):
    """Запрос выбора профиля"""
    u = message.from_user.id
    if not is_authenticated(u):
        await message.answer("⛔️ Не авторизованы. /login")
        return

    profiles = get_all_profiles()
    if not profiles:
        await message.answer("❌ Нет профилей")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=p.upper(), callback_data=f"run_{p}")]
            for p in profiles
        ]
    )

    await send_clean(bot, u, "📂 Выберите профиль для запуска:", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("run_"))
async def run_profile_callback(callback: types.CallbackQuery):
    """Обрабатывает выбор профиля"""
    user_id = callback.from_user.id
    if not is_authenticated(user_id):
        await callback.message.answer("⛔️ Не авторизованы. /login")
        await callback.answer()
        return

    # удаляем старые сообщения с inline-кнопками
    for msg_id in USER_MESSAGES.get(user_id, []):
        try:
            await callback.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except:
            pass
    USER_MESSAGES[user_id] = []

    profile_name = callback.data.split("_", 1)[1]
    await callback.message.answer(f"▶️ Запуск профиля: <b>{profile_name}</b>", parse_mode="HTML")

    reply = await start_trading(profile_name, trade_main_for_telegram)
    await callback.message.answer(f"🚀 Торговля запущена по профилю: <b>{profile_name}</b>", parse_mode="HTML")
    await callback.answer()

@router.message(lambda m: m.text == "⏹ Остановить")
async def cmd_stop(message: types.Message):
    """Останавливает торговлю"""
    if not is_authenticated(message.from_user.id):
        await message.answer("⛔️ Не авторизованы. /login")
        return
    reply = await stop_trading()
    await message.answer(reply)

@router.message(lambda m: m.text == "📤 Лог")
async def ask_log(message: types.Message):
    """Предлагает выбрать, сколько строк лога вывести"""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="📄 10", callback_data="log_10"),
            InlineKeyboardButton(text="📄 20", callback_data="log_20"),
            InlineKeyboardButton(text="📄 50", callback_data="log_50"),
        ]]
    )
    await message.answer("Сколько строк лога вывести?", reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("log_"))
async def show_log(callback: types.CallbackQuery):
    """Показывает строки лога"""
    count = int(callback.data.split("_", 1)[1])
    path = "trading.log"
    if not os.path.exists(path):
        await callback.message.answer("⚠️ Лог не найден.")
    else:
        lines = open(path, encoding="utf-8").read().splitlines()
        text = "\n".join(lines[-count:])
        await callback.message.answer(f"<pre>{text}</pre>", parse_mode="HTML")
    await callback.answer()

    
      

    