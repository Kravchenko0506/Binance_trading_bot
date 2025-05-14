# interfaces/telegram_bot/handlers.py

from aiogram import Router, types, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import os
import json

# Импортируем функции управления ботом из control_center
from bot_control.control_center import get_status, start_trading, stop_trading
# Импортируем функцию-обертку для запуска торговой логики
from run_trading_stream import trade_main_for_telegram
# Импортируем функцию для получения списка профилей и константу имени файла
from config.profile_loader import get_all_profiles, PROFILE_FILE

# Импортируем настроенный system_logger из централизованного модуля
from utils.logger import system_logger

router = Router()

# ───── КОНСТАНТЫ И ВРЕМЕННЫЕ СОСТОЯНИЯ ─────────────────────────────────────
AUTH_FILE = "config/auth.json" # Файл для хранения данных аутентификации
PENDING_AUTH = set()  # Множество user_id, ожидающих ввода пароля
USER_MESSAGES = {}    # Словарь: user_id -> [msg_id,...] для очистки предыдущих сообщений бота

# ───── ФУНКЦИИ АВТОРИЗАЦИИ ─────────────────────────────────────

def load_auth_data() -> dict:
    """Загружает auth.json или создаёт с нуля, обрабатывая возможные ошибки."""
    if not os.path.exists(AUTH_FILE):
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        data = {"passwords": {}, "users": {}}
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        system_logger.info(f"Файл {AUTH_FILE} не найден, создан новый.")
        return data
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        system_logger.error(f"Ошибка загрузки {AUTH_FILE}: {e}. Создаем новый файл.")
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        data = {"passwords": {}, "users": {}}
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data

def save_auth_data(data: dict):
    """Сохраняет auth.json, обрабатывая возможные ошибки."""
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        system_logger.error(f"Ошибка сохранения {AUTH_FILE}: {e}")

def is_authenticated(user_id: int) -> bool:
    """Проверка: есть ли user_id в списке users."""
    auth_data = load_auth_data()
    return str(user_id) in auth_data.get("users", {})

def verify_password(password: str) -> str | None:
    """Сверяет пароль. В вашей реализации возвращает значение, связанное с паролем (например, "api_key_placeholder")."""
    auth_data = load_auth_data()
    return auth_data.get("passwords", {}).get(password)

def register_user(user_id: int, api_key_placeholder: str):
    """Регистрирует Telegram ID пользователя."""
    data = load_auth_data()
    if "users" not in data: # Гарантируем существование ключа 'users'
        data["users"] = {}
    data["users"][str(user_id)] = api_key_placeholder # Сохраняем символическое значение
    save_auth_data(data)
    system_logger.info(f"Пользователь {user_id} зарегистрирован.")

# ───── УТИЛИТА: отправка и удаление старых сообщений ────────────

async def send_clean(bot: Bot, user_id: int, text: str, **kwargs):
    """
    Удаляет предыдущие сообщения бота для этого пользователя (из USER_MESSAGES)
    и отправляет новое сообщение, сохраняя его ID.
    """
    if user_id in USER_MESSAGES:
        for msg_id in USER_MESSAGES[user_id]:
            try:
                await bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception as e:
                system_logger.warning(f"Не удалось удалить сообщение {msg_id} для пользователя {user_id}: {e}")
        USER_MESSAGES[user_id] = []

    try:
        msg = await bot.send_message(chat_id=user_id, text=text, **kwargs)
        USER_MESSAGES.setdefault(user_id, []).append(msg.message_id)
    except Exception as e:
        system_logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

# ───── ГЕНЕРАЦИЯ МЕНЮ ───────────────────────────────────────────

def generate_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Генерирует основное меню с кнопками."""
    # auth = is_authenticated(user_id) # Проверка аутентификации здесь не нужна для генерации кнопок
    kb = [
        [KeyboardButton(text="▶️ Запустить"), KeyboardButton(text="⏹ Остановить")],
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📤 Лог")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False)

# ───── ОБРАБОТЧИКИ КОМАНД ───────────────────────────────────────

@router.message(Command("start", "help"))
async def cmd_start(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    system_logger.info(f"Получена команда /start от user_id: {user_id} ({user_name})")

    if not is_authenticated(user_id):
        await message.answer(f"👋 Привет, {user_name}! Чтобы получить доступ к боту, отправь команду /login")
        return

    await send_clean(
        bot,
        user_id,
        f"✅ Добро пожаловать, {user_name}! Вы авторизованы.\nВыберите действие в меню:",
        reply_markup=generate_main_menu(user_id)
    )

@router.message(Command("menu"))
async def cmd_menu(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    system_logger.info(f"Получена команда /menu от user_id: {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Вы не авторизованы. Используйте /login")
        return
    await send_clean(bot, user_id, "📋 Главное меню:", reply_markup=generate_main_menu(user_id))

@router.message(Command("login"))
async def cmd_login(message: types.Message):
    user_id = message.from_user.id
    system_logger.info(f"Получена команда /login от user_id: {user_id}")
    if is_authenticated(user_id):
        await message.answer("✅ Вы уже авторизованы. Используйте /start для отображения меню.")
        return
    PENDING_AUTH.add(user_id)
    await message.answer("🔒 Пожалуйста, введите ваш пароль доступа:")

@router.message(lambda message: message.from_user.id in PENDING_AUTH)
async def process_password(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    password_attempt = message.text.strip()
    system_logger.info(f"Получен пароль '{password_attempt}' от user_id: {user_id}")

    PENDING_AUTH.discard(user_id)
    
    api_key_placeholder = verify_password(password_attempt)
    if api_key_placeholder is not None:
        register_user(user_id, api_key_placeholder)
        system_logger.info(f"Успешная аутентификация для user_id: {user_id}")
        await send_clean(
            bot,
            user_id,
            "🎉 Пароль верный! Добро пожаловать. Теперь вам доступны команды управления ботом.",
            reply_markup=generate_main_menu(user_id)
        )
    else:
        system_logger.warning(f"Неудачная попытка аутентификации для user_id: {user_id} (пароль: '{password_attempt}')")
        await message.answer("❌ Неверный пароль. Попробуйте снова, отправив команду /login")

# ───── ОБРАБОТЧИКИ КНОПОК ОСНОВНОГО МЕНЮ ────────────────────────

@router.message(lambda message: message.text == "📊 Статус")
async def handle_show_status_button(message: types.Message):
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Статус' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return
    await show_detailed_status(message) # Вызываем отдельную функцию для отображения статуса

async def show_detailed_status(message: types.Message):
    """Отображает подробный статус торговли, используя HTML для форматирования."""
    system_logger.info(f"Запрос детального статуса для пользователя {message.from_user.id}")
    try:
        status_info = get_status()
        status_text = f"📊 <b>Текущий Статус Бота</b> 📊\n\n"
        status_text += f"<b>Состояние:</b> {'✅ <i>Работает</i>' if status_info.get('running') else '⛔️ <i>Остановлен</i>'}\n"
        status_text += f"<b>Активный профиль:</b> <code>{status_info.get('profile', 'Не выбран')}</code>\n\n"
        status_text += f"<b>Компоненты:</b>\n"
        status_text += f"  - Основная задача (<code>main_task</code>): <code>{status_info.get('main_task_status', 'N/A')}</code>\n"
        status_text += f"  - Слушатель цен (<code>listener_task</code>): <code>{status_info.get('listener_task_status', 'N/A')}</code>\n"
        status_text += f"  - Обработчик цен (<code>processor_task</code>): <code>{status_info.get('processor_task_status', 'N/A')}</code>\n"
        stop_event_status = status_info.get('stop_event_is_set', 'N/A')
        status_text += f"  - Сигнал остановки (<code>stop_event</code>): <code>{stop_event_status}</code>\n"

        await message.answer(status_text, parse_mode="HTML") # ИЗМЕНЕНО: parse_mode на HTML
    except Exception as e:
        system_logger.error(f"Ошибка при получении или отображении статуса для user_id {message.from_user.id}: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось получить статус бота. Пожалуйста, проверьте системные логи или попробуйте позже.")

@router.message(lambda message: message.text == "▶️ Запустить")
async def handle_run_button(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Запустить' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    try:
        profiles = get_all_profiles()
        if not profiles:
            await message.answer(f"❌ Не найдены торговые профили в файле <code>{PROFILE_FILE}</code>. Сначала создайте хотя бы один профиль.", parse_mode="HTML")
            return

        buttons = [[InlineKeyboardButton(text=profile_name.upper(), callback_data=f"runprofile_{profile_name}")] for profile_name in profiles]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_clean(bot, user_id, "📂 Выберите профиль для запуска:", reply_markup=keyboard)
    except FileNotFoundError:
        system_logger.error(f"Файл профилей '{PROFILE_FILE}' не найден при попытке запуска пользователем {user_id}.")
        await message.answer(f"❌ Ошибка: Файл конфигурации профилей (<code>{PROFILE_FILE}</code>) не найден.", parse_mode="HTML")
    except Exception as e:
        system_logger.error(f"Ошибка при получении списка профилей для user_id {user_id}: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при загрузке доступных профилей.")

@router.callback_query(lambda c: c.data.startswith("runprofile_"))
async def handle_run_profile_callback(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    profile_name = callback.data.split("_", 1)[1]
    system_logger.info(f"Пользователь {user_id} выбрал запуск профиля '{profile_name}'.")

    if not is_authenticated(user_id):
        await callback.message.answer("⛔️ Не авторизованы. Используйте /login")
        await callback.answer("Действие недоступно", show_alert=True)
        return

    try: # Удаляем сообщение с инлайн-кнопками
        await bot.delete_message(chat_id=user_id, message_id=callback.message.message_id)
        if user_id in USER_MESSAGES: USER_MESSAGES[user_id] = [] # Очищаем для send_clean
    except Exception as e:
        system_logger.warning(f"Не удалось удалить сообщение {callback.message.message_id} с кнопками выбора профиля для user_id {user_id}: {e}")

    await bot.send_message(chat_id=user_id, text=f"⏳ Запускаем торговый профиль: <code>{profile_name}</code>...", parse_mode="HTML")
    
    response_from_start = f"Запрос на запуск профиля '{profile_name}' отправлен." # Ответ по умолчанию для callback.answer
    try:
        system_logger.info(f"--> Вызов control_center.start_trading для профиля '{profile_name}' (user_id: {user_id}).")
        response_from_start = await start_trading(profile_name, trade_main_for_telegram)
        system_logger.info(f"<-- control_center.start_trading для профиля '{profile_name}' (user_id: {user_id}) вернул: {response_from_start}")
        await bot.send_message(chat_id=user_id, text=response_from_start)
    except Exception as e:
        system_logger.error(f"Критическая ошибка при вызове или во время start_trading для '{profile_name}' (user_id: {user_id}): {e}", exc_info=True)
        error_message = f"❌ Ошибка запуска профиля <code>{profile_name}</code>. Подробности в системном логе."
        await bot.send_message(chat_id=user_id, text=error_message, parse_mode="HTML")
        response_from_start = "Ошибка запуска." # Обновляем для callback.answer
    finally:
        await callback.answer(response_from_start, show_alert=isinstance(response_from_start, str) and "Ошибка" in response_from_start)

    # Восстанавливаем главное меню
    await send_clean(bot, user_id, "Выберите следующее действие:", reply_markup=generate_main_menu(user_id))


@router.message(lambda message: message.text == "⏹ Остановить")
async def handle_stop_button(message: types.Message, bot: Bot): # Добавил bot для send_clean
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Остановить' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    await message.answer("⏳ Останавливаем торговую сессию...")
    response_from_stop = "Запрос на остановку обработан." # Ответ по умолчанию
    try:
        response_from_stop = await stop_trading()
        await message.answer(response_from_stop)
    except Exception as e:
        system_logger.error(f"Ошибка при вызове stop_trading пользователем {user_id}: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при попытке остановки. Подробности в системном логе.")
    
    # Восстанавливаем главное меню
    await send_clean(bot, user_id, "Выберите следующее действие:", reply_markup=generate_main_menu(user_id))


@router.message(lambda message: message.text == "📤 Лог")
async def handle_ask_log_button(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Лог' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 system (10)", callback_data="log_system_10"),
                InlineKeyboardButton(text="📄 system (30)", callback_data="log_system_30"),
            ],
            [
                InlineKeyboardButton(text="📈 trading (10)", callback_data="log_trading_10"),
                InlineKeyboardButton(text="📈 trading (30)", callback_data="log_trading_30"),
            ]
        ]
    )
    await send_clean(bot, user_id, "📜 Выберите тип и количество строк лога для просмотра:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("log_"))
async def handle_show_log_callback(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if not is_authenticated(user_id):
        await callback.message.answer("⛔️ Не авторизованы. Используйте /login")
        await callback.answer("Действие недоступно", show_alert=True)
        return

    response_text_for_callback = "Лог обработан."
    try:
        parts = callback.data.split("_")
        log_type = parts[1]
        count = int(parts[2])
    except (IndexError, ValueError):
        system_logger.error(f"Некорректный callback_data для лога от user_id {user_id}: {callback.data}")
        await callback.answer("Ошибка данных запроса лога.", show_alert=True)
        return

    system_logger.info(f"Пользователь {user_id} запросил лог '{log_type}', последние {count} строк.")

    log_path = f"logs/{log_type}.log" # Динамическое формирование пути к логу
    # Убедись, что имена файлов system.log и trading_activity.log (или trading.log) используются консистентно

    try: # Удаляем сообщение с инлайн-кнопками
        await bot.delete_message(chat_id=user_id, message_id=callback.message.message_id)
        if user_id in USER_MESSAGES: USER_MESSAGES[user_id] = []
    except Exception as e:
        system_logger.warning(f"Не удалось удалить сообщение {callback.message.message_id} с кнопками выбора лога для user_id {user_id}: {e}")

    if not os.path.exists(log_path):
        await bot.send_message(chat_id=user_id, text=f"⚠️ Файл лога <code>{log_path}</code> не найден.", parse_mode="HTML")
        response_text_for_callback = "Файл лога не найден."
    else:
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            last_lines = lines[-count:]
            
            if not last_lines:
                 await bot.send_message(chat_id=user_id, text=f"ℹ️ Лог-файл <code>{log_path}</code> пуст.", parse_mode="HTML")
                 response_text_for_callback = "Лог пуст."
            else:
                log_text = f"📜 <b>Лог:</b> <code>{log_path}</code> (последние {len(last_lines)} строк)\n<pre>"
                log_text += "".join(last_lines).replace("<", "&lt;").replace(">", "&gt;") # Экранируем HTML в тексте лога
                log_text += "</pre>"

                if len(log_text) > 4000: # Оставляем запас для тегов и т.д.
                    log_text = log_text[:4000] + "... (лог обрезан)</pre>"
                    system_logger.warning(f"Лог '{log_path}' для пользователя {user_id} был обрезан из-за длины.")
                
                await bot.send_message(chat_id=user_id, text=log_text, parse_mode="HTML")
                response_text_for_callback = "Лог отправлен."
        except Exception as e:
            system_logger.error(f"Ошибка чтения или отправки лога '{log_path}' пользователю {user_id}: {e}", exc_info=True)
            await bot.send_message(chat_id=user_id, text=f"❌ Произошла ошибка при чтении или отправке лога <code>{log_path}</code>.", parse_mode="HTML")
            response_text_for_callback = "Ошибка чтения лога."
            
    await callback.answer(response_text_for_callback, show_alert="Ошибка" in response_text_for_callback)

    # Восстанавливаем главное меню
    await send_clean(bot, user_id, "Выберите следующее действие:", reply_markup=generate_main_menu(user_id))

    
      

    