# utils/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
# Убедимся, что директория для логов существует
os.makedirs(LOG_DIR, exist_ok=True)

# --- Общая функция для настройки логгеров ---
def configure_logger(
    logger_name: str,
    log_file: str,
    level: int = logging.INFO,
    formatter_string: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 5,
    add_console_handler: bool = False  # По умолчанию не добавляем консольный вывод для всех логгеров
):
    """
    Configures and returns a logger instance with file rotation.
    Prevents duplicate handlers from being added.
    """
    logger = logging.getLogger(logger_name)


    if not logger.level or logger.level > level:
        logger.setLevel(level)

    has_file_handler_for_this_file = any(
        isinstance(h, logging.FileHandler) and os.path.abspath(h.baseFilename) == os.path.abspath(log_file)
        for h in logger.handlers
    )

    if not has_file_handler_for_this_file:
        # Файловый обработчик с ротацией
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        formatter = logging.Formatter(formatter_string)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if add_console_handler:
        has_console_handler = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers)
        if not has_console_handler:
            console_formatter = logging.Formatter(formatter_string if formatter_string else '%(levelname)s: %(message)s')
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(level) # Уровень для консоли может быть таким же или другим
            logger.addHandler(console_handler)
            
    return logger

#  Initializing specific loggers for the project
system_logger = configure_logger(
    logger_name="system",
    log_file=os.path.join(LOG_DIR, "system.log"),
    level=logging.DEBUG,
    add_console_handler=True, # Системные сообщения важны в консоли
    formatter_string='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s' # Добавим номер строки
)
trading_logger = configure_logger(
    logger_name="trading", # или "trading_log", если ты использовал это имя
    log_file=os.path.join(LOG_DIR, "trading.log"),
    level=logging.DEBUG,
    add_console_handler=True 
)

test_logger = configure_logger(
    logger_name="test", # или "trading_log", если ты использовал это имя
    log_file=os.path.join(LOG_DIR, "trading-test.log"),
    level=logging.DEBUG,
    add_console_handler=True 
)

def get_system_logger():
    return system_logger

def get_trading_logger():
    return trading_logger

def get_test_logger():
    return test_logger

system_logger.info("Логгер 'system' успешно настроен.")
trading_logger.info("Логгер 'trading' успешно настроен.")
test_logger.info("Логгер 'test' успешно настроен.")
