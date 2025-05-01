import logging
from colorama import Fore, Style, init

init(autoreset=True)

def setup_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Вывод в файл
    file_handler = logging.FileHandler('trading_bot.log', encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    # Вывод в консоль с цветами
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
