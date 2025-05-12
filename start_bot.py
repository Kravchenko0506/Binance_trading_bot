# start_bot.py (Исправленная версия)

import asyncio
import sys # Добавим для sys.exit в случае критической ошибки импорта

try:
    from interfaces.telegram_bot.bot_entry import main as bot_entry_main
    # Также импортируем логгер для использования в этом файле
    from utils.logger import system_logger
    # Импортируем logging для финального shutdown
    import logging
except ImportError as e:
    # Если импорты не срабатывают, выводим ошибку и выходим, т.к. бот не сможет запуститься
    print(f"Критическая ошибка импорта: {e}")
    print("Убедитесь, что структура проекта и файлы 'interfaces/telegram_bot/bot_entry.py' и 'utils/logger.py' существуют и корректны.")
    sys.exit(1) # Выход с кодом ошибки
except Exception as e:
    print(f"Критическая ошибка при инициализации импортов: {e}")
    sys.exit(1)

# ▶ Точка входа основного скрипта запуска бота
if __name__ == '__main__':
    # Логируем начало запуска именно этого скрипта
    system_logger.info("="*20 + " Запуск основного скрипта start_bot.py " + "="*20)

    try:
        # --- ИСПРАВЛЕНИЕ ВЫЗОВА ---
        # Вместо: asyncio.run(start_aiogram_bot())
        # Запускаем импортированную функцию bot_entry_main
        asyncio.run(bot_entry_main())

    except KeyboardInterrupt:
        # Обработка Ctrl+C на самом верхнем уровне, если signal_handler по какой-то причине не сработал
        # или если KeyboardInterrupt произошел до запуска asyncio.run или после его завершения.
        system_logger.info("Скрипт start_bot.py прерван пользователем (KeyboardInterrupt).")
        print("\nПрограмма прервана пользователем.")
    except Exception as e:
        # Ловим любые другие неперехваченные исключения на самом верху
        system_logger.critical(f"Критическая неперехваченная ошибка в start_bot.py: {e}", exc_info=True)
        print(f"\nКритическая ошибка: {e}")
    finally:
        # Финальное сообщение о завершении работы скрипта
        system_logger.info("="*20 + " Завершение работы скрипта start_bot.py " + "="*20)
        # Дополнительная гарантия закрытия логов
        if logging.getLogger().handlers:
            logging.shutdown()