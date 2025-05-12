# interfaces/telegram_bot/handlers.py

from aiogram import Router, types, Bot
from aiogram.filters import Command, CommandObject # Добавим CommandObject для /start_profile
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import os
import json # Импорт json уже был

# Импортируем функции управления ботом из control_center
from bot_control.control_center import get_status, start_trading, stop_trading
# Импортируем функцию-обертку для запуска торговой логики
from run_trading_stream import trade_main_for_telegram
# Импортируем функцию для получения списка профилей
from config.profile_loader import get_all_profiles, PROFILE_FILE # Добавим PROFILE_FILE для сообщения об отсутствии

# Импортируем настроенный system_logger из централизованного модуля
from utils.logger import system_logger # Раскомментировано

router = Router()

# ───── КОНСТАНТЫ И ВРЕМЕННЫЕ СОСТОЯНИЯ ─────────────────────────────────────
AUTH_FILE = "config/auth.json" # Файл для хранения данных аутентификации
PENDING_AUTH = set()  # Множество user_id, ожидающих ввода пароля
USER_MESSAGES = {}    # Словарь: user_id -> [msg_id,...] для очистки предыдущих сообщений бота

# ───── ФУНКЦИИ АВТОРИЗАЦИИ (без изменений) ─────────────────────────────────────

def load_auth_data() -> dict:
    """Загружает auth.json или создаёт с нуля"""
    if not os.path.exists(AUTH_FILE):
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        data = {"passwords": {}, "users": {}}
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        system_logger.error(f"Ошибка загрузки auth.json: {e}. Создаем новый файл.")
        # В случае ошибки создаем пустой файл
        os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
        data = {"passwords": {}, "users": {}}
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data


def save_auth_data(data: dict):
    """Сохраняет auth.json"""
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        system_logger.error(f"Ошибка сохранения auth.json: {e}")

def is_authenticated(user_id: int) -> bool:
    """Проверка: есть ли user_id в списке users"""
    auth_data = load_auth_data()
    return str(user_id) in auth_data.get("users", {})

def verify_password(password: str) -> str | None:
    """Сверяет пароль → возвращает API-ключ (в вашей реализации он не используется напрямую из пароля)"""
    # В вашей реализации пароль просто проверяется на наличие ключа
    auth_data = load_auth_data()
    return auth_data.get("passwords", {}).get(password) # Возвращает "api_key" или None

def register_user(user_id: int, api_key_value: str): # Имя второго аргумента изменено для ясности
    """Регистрирует Telegram ID пользователя. api_key_value здесь символический, может быть просто True или имя пароля"""
    data = load_auth_data()
    # Гарантируем, что словарь 'users' существует
    if "users" not in data:
        data["users"] = {}
    data["users"][str(user_id)] = api_key_value # Сохраняем флаг или ключ API
    save_auth_data(data)
    system_logger.info(f"Пользователь {user_id} зарегистрирован.")

# ───── УТИЛИТА: отправка и удаление старых сообщений (без изменений) ────────────

async def send_clean(bot: Bot, user_id: int, text: str, **kwargs):
    """
    Удаляет предыдущие сообщения бота для этого пользователя (из USER_MESSAGES)
    и отправляет новое сообщение, сохраняя его ID.
    """
    # Удалить ВСЕ старые сообщения пользователя, если есть
    if user_id in USER_MESSAGES:
        for msg_id in USER_MESSAGES[user_id]:
            try:
                await bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception as e:
                # Логируем ошибку удаления, но не прерываем работу
                system_logger.warning(f"Не удалось удалить сообщение {msg_id} для пользователя {user_id}: {e}")
        USER_MESSAGES[user_id] = [] # Очищаем список старых сообщений

    # Отправить новое сообщение и сохранить ID
    try:
        msg = await bot.send_message(chat_id=user_id, text=text, **kwargs)
        # Добавляем ID нового сообщения в список для последующей очистки
        USER_MESSAGES.setdefault(user_id, []).append(msg.message_id)
    except Exception as e:
        system_logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")


# ───── ГЕНЕРАЦИЯ МЕНЮ (без изменений) ───────────────────────────────────────────

def generate_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Меню: динамически показывает регистрацию или команды"""
    auth = is_authenticated(user_id)
    kb = [
        [KeyboardButton(text="▶️ Запустить"), KeyboardButton(text="⏹ Остановить")],
        [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📤 Лог")]
    ]
    # Кнопка регистрации/логина показывается только неавторизованным пользователям
    # Логика login/register обрабатывается отдельными командами /login
    # if not auth:
    #     kb.append([KeyboardButton(text="🔐 Зарегистрироваться")]) # Логика регистрации через /login
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=False) # one_time_keyboard=False, чтобы меню не скрывалось

# ───── ОБРАБОТЧИКИ КОМАНД ───────────────────────────────────────

@router.message(Command("start", "help"))
async def cmd_start(message: types.Message, bot: Bot):
    """Команда /start или /help: показывает приветствие и меню"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    system_logger.info(f"Получена команда /start от user_id: {user_id} ({user_name})")

    if not is_authenticated(user_id):
        await message.answer(f"👋 Привет, {user_name}! Чтобы получить доступ к боту, отправь команду /login")
        return

    # Используем send_clean для обновления меню
    await send_clean(
        bot,
        user_id,
        f"✅ Добро пожаловать, {user_name}! Вы авторизованы.\nВыберите действие в меню:",
        reply_markup=generate_main_menu(user_id)
    )

@router.message(Command("menu"))
async def cmd_menu(message: types.Message, bot: Bot):
    """Команда /menu: принудительно перерисовать меню"""
    user_id = message.from_user.id
    system_logger.info(f"Получена команда /menu от user_id: {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Вы не авторизованы. Используйте /login")
        return
    await send_clean(bot, user_id, "📋 Главное меню:", reply_markup=generate_main_menu(user_id))

@router.message(Command("login"))
async def cmd_login(message: types.Message):
    """Команда /login: запрашивает пароль"""
    user_id = message.from_user.id
    system_logger.info(f"Получена команда /login от user_id: {user_id}")
    if is_authenticated(user_id):
        await message.answer("✅ Вы уже авторизованы. Используйте /start для отображения меню.")
        return
    # Добавляем пользователя в множество ожидающих ввода пароля
    PENDING_AUTH.add(user_id)
    await message.answer("🔒 Пожалуйста, введите ваш пароль доступа:")

# Обработчик для сообщений от пользователей, ожидающих аутентификации
@router.message(lambda message: message.from_user.id in PENDING_AUTH)
async def process_password(message: types.Message, bot: Bot):
    """Обрабатывает введенный пароль, если пользователь в PENDING_AUTH"""
    user_id = message.from_user.id
    password_attempt = message.text.strip()
    system_logger.info(f"Получен пароль от user_id: {user_id}")

    # Удаляем пользователя из ожидания независимо от результата
    PENDING_AUTH.discard(user_id)
    
    # Проверяем пароль
    api_key_value = verify_password(password_attempt) # api_key_value может быть символическим
    if api_key_value is not None:
        # Регистрируем пользователя
        register_user(user_id, api_key_value) # Сохраняем пользователя как авторизованного
        system_logger.info(f"Успешная аутентификация для user_id: {user_id}")
        # Отправляем подтверждение и меню
        await send_clean(
            bot,
            user_id,
            "🎉 Пароль верный! Добро пожаловать. Теперь вам доступны команды управления ботом.",
            reply_markup=generate_main_menu(user_id)
        )
    else:
        system_logger.warning(f"Неудачная попытка аутентификации для user_id: {user_id}")
        await message.answer("❌ Неверный пароль. Попробуйте снова, отправив команду /login")

# ───── ОБРАБОТЧИКИ КНОПОК ОСНОВНОГО МЕНЮ ────────────────────────

@router.message(lambda message: message.text == "📊 Статус")
async def handle_show_status_button(message: types.Message):
    """Обрабатывает нажатие кнопки 'Статус' """
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Статус' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    # Вызываем обновленный обработчик статуса
    await show_detailed_status(message)


async def show_detailed_status(message: types.Message):
    """Отображает подробный статус торговли (вызывается из обработчика кнопки)"""
    try:
        status_info = get_status() # Получаем расширенный статус из control_center
        # Форматируем статус для вывода
        status_text = f"📊 **Текущий Статус Бота** 📊\n\n"
        status_text += f"**Состояние:** {'✅ *Работает*' if status_info['running'] else '⛔️ *Остановлен*'}\n"
        status_text += f"**Активный профиль:** `{status_info['profile'] if status_info['profile'] else 'Не выбран'}`\n\n"
        
        # Добавляем детали о задачах и событии остановки
        status_text += f"**Компоненты:**\n"
        status_text += f"  - Основная задача (`main_task`): `{status_info.get('main_task_status', 'N/A')}`\n"
        status_text += f"  - Слушатель цен (`listener_task`): `{status_info.get('listener_task_status', 'N/A')}`\n"
        status_text += f"  - Обработчик цен (`processor_task`): `{status_info.get('processor_task_status', 'N/A')}`\n"
        status_text += f"  - Сигнал остановки (`stop_event`): `{status_info.get('stop_event_is_set', 'N/A')}`\n"

        # Можно добавить время последнего обновления, PnL и т.д., когда они будут доступны

        await message.answer(status_text, parse_mode="MarkdownV2") # Используем Markdown для форматирования

    except Exception as e:
        system_logger.error(f"Ошибка при получении или отображении статуса: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось получить статус бота. Попробуйте позже.")


@router.message(lambda message: message.text == "▶️ Запустить")
async def handle_run_button(message: types.Message, bot: Bot):
    """Обрабатывает нажатие кнопки 'Запустить', показывает выбор профиля"""
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Запустить' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    try:
        profiles = get_all_profiles() # Загружаем список имен профилей
        if not profiles:
            await message.answer(f"❌ Не найдены торговые профили в файле `{PROFILE_FILE}`. Сначала создайте профиль.")
            return

        # Создаем инлайн-клавиатуру с кнопками для каждого профиля
        buttons = [
            [InlineKeyboardButton(text=profile_name.upper(), callback_data=f"runprofile_{profile_name}")]
            for profile_name in profiles
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        # Используем send_clean для отправки сообщения с кнопками
        await send_clean(bot, user_id, "📂 Выберите профиль для запуска:", reply_markup=keyboard)

    except FileNotFoundError:
        system_logger.error(f"Файл профилей '{PROFILE_FILE}' не найден при попытке запуска пользователем {user_id}.")
        await message.answer(f"❌ Ошибка: Файл конфигурации профилей (`{PROFILE_FILE}`) не найден.")
    except Exception as e:
        system_logger.error(f"Ошибка при получении списка профилей: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при загрузке профилей.")


@router.callback_query(lambda c: c.data.startswith("runprofile_"))
async def handle_run_profile_callback(callback: types.CallbackQuery, bot: Bot): # Добавляем bot как аргумент
    """Обрабатывает нажатие инлайн-кнопки с выбором профиля"""
    user_id = callback.from_user.id
    profile_name = callback.data.split("_", 1)[1] # Извлекаем имя профиля из callback_data
    system_logger.info(f"Пользователь {user_id} выбрал запуск профиля '{profile_name}'.")

    if not is_authenticated(user_id):
        await callback.message.answer("⛔️ Не авторизованы. Используйте /login")
        await callback.answer("Действие недоступно") # Отвечаем на callback, чтобы убрать "часики"
        return

    # Попытка удалить сообщение с кнопками выбора профиля
    try:
        await bot.delete_message(chat_id=user_id, message_id=callback.message.message_id)
        # Также очищаем список старых сообщений в USER_MESSAGES, если там что-то было
        if user_id in USER_MESSAGES:
            USER_MESSAGES[user_id] = []
    except Exception as e:
        system_logger.warning(f"Не удалось удалить сообщение {callback.message.message_id} с кнопками выбора профиля: {e}")

    # Отправляем подтверждение о начале запуска
    await bot.send_message( # Используем bot.send_message вместо callback.message.answer для нового сообщения
        chat_id=user_id,
        text=f"⏳ Запускаем торговый профиль: **`{profile_name}`**...",
        parse_mode="MarkdownV2"
    )

    try:
        # Вызываем функцию запуска торговли из control_center
        # Передаем имя профиля и корутину-раннер (trade_main_for_telegram)
        # system_logger больше не передается явно, control_center использует свой импортированный
        response_from_start = await start_trading(profile_name, trade_main_for_telegram)
        
        # Отправляем результат пользователю
        await bot.send_message(chat_id=user_id, text=response_from_start) # Отправляем ответ от start_trading
        
    except Exception as e:
        # Обрабатываем возможные ошибки на этапе запуска
        system_logger.error(f"Ошибка при вызове start_trading для профиля '{profile_name}' пользователем {user_id}: {e}", exc_info=True)
        await bot.send_message(chat_id=user_id, text=f"❌ Произошла ошибка при попытке запуска профиля `{profile_name}`. Проверьте логи.")

    # Отвечаем на исходный callback, чтобы убрать "часики" на кнопке
    await callback.answer("Запрос на запуск отправлен.")


@router.message(lambda message: message.text == "⏹ Остановить")
async def handle_stop_button(message: types.Message):
    """Обрабатывает нажатие кнопки 'Остановить'"""
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Остановить' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    await message.answer("⏳ Останавливаем торговую сессию...") # Уведомление о начале остановки
    try:
        # Вызываем функцию остановки из control_center
        # system_logger больше не передается явно
        reply = await stop_trading()
        await message.answer(reply) # Отправляем результат пользователю
    except Exception as e:
        system_logger.error(f"Ошибка при вызове stop_trading пользователем {user_id}: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при попытке остановки. Проверьте логи.")


@router.message(lambda message: message.text == "📤 Лог")
async def handle_ask_log_button(message: types.Message, bot: Bot): # Добавляем bot
    """Обрабатывает нажатие кнопки 'Лог', предлагает выбор строк"""
    user_id = message.from_user.id
    system_logger.info(f"Нажата кнопка 'Лог' пользователем {user_id}")
    if not is_authenticated(user_id):
        await message.answer("⛔️ Не авторизованы. Используйте /login")
        return

    # Создаем инлайн-кнопки для выбора количества строк
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [ # Первый ряд кнопок
                InlineKeyboardButton(text="📄 system (10)", callback_data="log_system_10"),
                InlineKeyboardButton(text="📄 system (30)", callback_data="log_system_30"),
            ],
            [ # Второй ряд кнопок
                InlineKeyboardButton(text="📈 trading (10)", callback_data="log_trading_10"),
                InlineKeyboardButton(text="📈 trading (30)", callback_data="log_trading_30"),
            ]
        ]
    )
    # Используем send_clean для отправки сообщения с кнопками
    await send_clean(bot, user_id, "📜 Выберите тип и количество строк лога для просмотра:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data.startswith("log_"))
async def handle_show_log_callback(callback: types.CallbackQuery, bot: Bot): # Добавляем bot
    """Обрабатывает нажатие инлайн-кнопки для показа лога"""
    user_id = callback.from_user.id
    if not is_authenticated(user_id):
        await callback.message.answer("⛔️ Не авторизованы. Используйте /login")
        await callback.answer("Действие недоступно")
        return

    try:
        parts = callback.data.split("_") # Разбираем callback_data, например "log_system_10"
        log_type = parts[1] # "system" или "trading"
        count = int(parts[2]) # 10 или 30
    except (IndexError, ValueError):
        system_logger.error(f"Некорректный callback_data для лога: {callback.data}")
        await callback.answer("Ошибка данных запроса лога.")
        return

    system_logger.info(f"Пользователь {user_id} запросил лог '{log_type}', последние {count} строк.")

    # Определяем путь к файлу лога в зависимости от типа
    if log_type == "system":
        log_path = "logs/system.log"
    elif log_type == "trading":
        # Используйте имя файла, которое вы задали в utils.logger для trading_logger
        log_path = "logs/trading_activity.log" # или logs/trading_log.log
    else:
        await callback.message.answer("⚠️ Неизвестный тип лога.")
        await callback.answer("Ошибка типа лога.")
        return

    # Попытка удалить сообщение с кнопками выбора лога
    try:
        await bot.delete_message(chat_id=user_id, message_id=callback.message.message_id)
        if user_id in USER_MESSAGES:
            USER_MESSAGES[user_id] = []
    except Exception as e:
        system_logger.warning(f"Не удалось удалить сообщение {callback.message.message_id} с кнопками выбора лога: {e}")

    if not os.path.exists(log_path):
        await bot.send_message(chat_id=user_id, text=f"⚠️ Файл лога `{log_path}` не найден.")
    else:
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines() # Читаем все строки

            # Берем последние 'count' строк
            last_lines = lines[-count:]
            
            if not last_lines:
                 await bot.send_message(chat_id=user_id, text=f"ℹ️ Лог-файл `{log_path}` пуст.")
                 await callback.answer("Лог пуст.")
                 return

            # Формируем текст для отправки
            # Используем ``` для моноширинного блока, он лучше подходит для логов, чем <pre>
            log_text = f"📜 **Лог: `{log_path}` (последние {len(last_lines)} строк)**\n```\n"
            log_text += "".join(last_lines) # Объединяем строки обратно
            log_text += "\n```"

            # Проверяем длину сообщения (Telegram лимит ~4096 символов)
            if len(log_text) > 4000: # Оставляем запас
                log_text = log_text[:4000] + "\n... (лог обрезан из-за длины)```"
                system_logger.warning(f"Лог для пользователя {user_id} был обрезан из-за превышения лимита длины.")

            await bot.send_message(chat_id=user_id, text=log_text, parse_mode="MarkdownV2") # Markdown для ```
        except Exception as e:
            system_logger.error(f"Ошибка чтения или отправки лога '{log_path}' пользователю {user_id}: {e}", exc_info=True)
            await bot.send_message(chat_id=user_id, text=f"❌ Произошла ошибка при чтении или отправке лога `{log_path}`.")

    # Отвечаем на callback, чтобы убрать "часики"
    await callback.answer("Лог отправлен.")

    
      

    