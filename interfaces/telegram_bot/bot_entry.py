# interfaces/telegram_bot/bot_entry.py

import asyncio
import signal
from aiogram.types import BotCommand

# Импортируем необходимые компоненты
from interfaces.telegram_bot.bot_config import bot, dp
from interfaces.telegram_bot.handlers import router
# Импортируем control_center для вызова stop_trading при завершении
from bot_control import control_center
# Импортируем system_logger из правильного места
from utils.logger import system_logger
# Импортируем logging для корректного shutdown логгера
import logging


# Флаг для индикации запроса на остановку из обработчика сигнала
shutdown_requested = False

async def set_bot_commands():
    """Задаёт системное меню команд в Telegram."""
    commands = [
        BotCommand(command="start", description="Начало работы / Главное меню"),
        BotCommand(command="menu", description="Показать/Обновить клавиатуру"),
        BotCommand(command="login", description="Авторизация по паролю"),
        # Можно добавить другие команды сюда
    ]
    try:
        await bot.set_my_commands(commands)
        system_logger.info("Системные команды Telegram успешно установлены.")
    except Exception as e:
        system_logger.error(f"Не удалось установить системные команды Telegram: {e}", exc_info=True)


async def main():
    """Основная асинхронная функция: настраивает и запускает бота."""
    # Включаем роутер с хендлерами
    dp.include_router(router)
    
    # Устанавливаем команды бота
    await set_bot_commands()
    
    system_logger.info("Запуск опроса Telegram (polling)...")
    try:
        # Запускаем основной цикл опроса Telegram
        await dp.start_polling(bot, skip_updates=True) # skip_updates=True может быть полезен при перезапуске
    except asyncio.CancelledError:
        # Это ожидаемо, если главная задача была отменена сигналом
        system_logger.info("Основной цикл опроса Telegram отменен (CancelledError).")
    except Exception as e:
        system_logger.critical(f"Критическая ошибка в главном цикле опроса Telegram: {e}", exc_info=True)
    finally:
        # --- Блок корректного завершения ---
        system_logger.info("Начало процедуры корректного завершения бота...")
        
        # 1. Останавливаем активную торговую сессию, если она есть
        system_logger.info("Попытка остановить торговую сессию (если активна)...")
        try:
            stop_response = await control_center.stop_trading() # Вызываем нашу функцию остановки
            system_logger.info(f"Результат остановки торговой сессии: {stop_response}")
        except Exception as e:
            system_logger.error(f"Ошибка при вызове control_center.stop_trading() во время завершения: {e}", exc_info=True)
            
        # 2. Закрываем сессию бота
        system_logger.info("Закрытие сессии aiogram бота...")
        try:
            await bot.session.close()
            system_logger.info("Сессия aiogram бота успешно закрыта.")
        except Exception as e:
            system_logger.error(f"Ошибка при закрытии сессии aiogram бота: {e}", exc_info=True)

        # 3. Закрываем систему логирования
        system_logger.info("Завершение работы системы логирования...")
        logging.shutdown()
        print("Logging system shut down.") # Вывод в консоль для подтверждения

        system_logger.info("Процедура корректного завершения бота завершена.")


def signal_handler(signum, frame):
    """
    Обработчик сигналов SIGINT (Ctrl+C) и SIGTERM.
    Он устанавливает флаг и отменяет главную задачу asyncio.
    """
    global shutdown_requested
    if not shutdown_requested:
        shutdown_requested = True
        system_logger.info(f"Получен сигнал завершения ({signal.Signals(signum).name}). Инициируем остановку asyncio...")
        print(f"\nПолучен сигнал {signal.Signals(signum).name}. Завершение работы...")
        
        # Находим все выполняющиеся задачи asyncio
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        if not tasks:
            system_logger.info("Не найдено активных задач asyncio для отмены.")
            # Если задач нет, возможно, цикл уже завершается, просто выходим
            # Можно попытаться вызвать loop.stop() если есть доступ к loop
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.stop()
                    system_logger.info("Цикл asyncio остановлен через loop.stop().")
            except RuntimeError: # Если цикл не запущен
                 system_logger.info("Цикл asyncio не запущен.")
            return

        system_logger.info(f"Найдено {len(tasks)} активных задач asyncio. Отменяем их...")
        # Отменяем все найденные задачи
        for task in tasks:
            task.cancel()
        system_logger.info("Все активные задачи asyncio помечены для отмены.")
    else:
        # Если сигнал получен повторно, возможно, стоит выйти принудительно
        system_logger.warning("Повторный сигнал завершения получен. Процесс может быть уже в стадии остановки.")


# ▶ Точка входа
if __name__ == "__main__":
    system_logger.info("="*20 + " Запуск Telegram бота (bot_entry.py) " + "="*20)
    
    # Настраиваем обработчики сигналов операционной системы
    # Они вызовут signal_handler, который отменит задачи asyncio
    signal.signal(signal.SIGINT, signal_handler)  # Обработка Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # Обработка сигнала завершения (например, от systemd)

    try:
        # Запускаем основную асинхронную функцию main()
        asyncio.run(main())
    except KeyboardInterrupt:
        # Этот блок может и не выполниться, т.к. SIGINT обрабатывается signal_handler,
        # который отменяет задачи asyncio, что приводит к завершению asyncio.run() через CancelledError внутри main.
        system_logger.info("Программа прервана (KeyboardInterrupt в __main__).")
    except Exception as e:
        system_logger.critical(f"Критическая неперехваченная ошибка в __main__: {e}", exc_info=True)
    finally:
        system_logger.info("="*20 + " Завершение работы Telegram бота (bot_entry.py) " + "="*20)
        # Дополнительная гарантия закрытия логов, хотя logging.shutdown() уже есть в main()
        if logging.getLogger().handlers: # Проверяем, есть ли еще обработчики
            logging.shutdown()

