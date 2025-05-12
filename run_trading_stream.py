import asyncio
import threading
import sys
import logging
from types import SimpleNamespace
from config.profile_loader import get_profile_by_name
from services.binance_stream import listen_klines
from services.order_execution import place_order
from services.technical_indicators import talib
from utils.logger import system_logger,trading_logger
from bot_control.control_center import CURRENT_STATE
from types import SimpleNamespace

async def price_processor(queue: asyncio.Queue, profile):
    """Обрабатывает цены из очереди и принимает торговые решения."""
    try:
        while True:
            price = await queue.get() # Ожидаем новую цену из очереди
            system_logger.debug(f"Price processor ({profile.SYMBOL}): получена цена {price}") # Пример логирования

            # Здесь должна быть твоя логика проверки сигналов и размещения ордеров
            # action = check_buy_sell_signals(profile, price) # Возможно, нужно передавать цену
            # if action != 'hold':
            #     place_order(action, profile.SYMBOL, profile.COMMISSION_RATE)
            
            queue.task_done() # Сообщаем очереди, что элемент обработан
    except asyncio.CancelledError:
        system_logger.info(f"Price processor ({profile.SYMBOL}): Задача отменена.")
        # Здесь можно добавить логику для закрытия открытых позиций, если это необходимо при отмене
    except Exception as e:
        system_logger.error(f"Price processor ({profile.SYMBOL}): Непредвиденная ошибка: {e}", exc_info=True)
    finally:
        system_logger.info(f"Price processor ({profile.SYMBOL}): Завершение работы.")


async def trade_main(profile: SimpleNamespace):
    """
    Основная асинхронная функция для запуска торговой логики для одного профиля.
    Создает stop_event, запускает listen_klines и price_processor.
    Обрабатывает отмену и другие исключения для корректного завершения.
    """
    # setup_logger() - этот вызов здесь больше не нужен, т.к. логгеры инициализируются в utils.logger

    system_logger.info(f"trade_main ({profile.SYMBOL}): Запуск торговли для профиля.")
    
    # Создаем событие для управления остановкой фоновых потоков/задач
    stop_event = threading.Event()
    # Создаем очередь для передачи цен от listen_klines к price_processor
    price_queue = asyncio.Queue()
    
    # Инициализируем переменные для задач, чтобы к ним был доступ в finally
    listener_task = None
    processor_task = None

    # --- Регистрация компонентов в CURRENT_STATE ---
    # Это важно сделать до первого await, чтобы control_center имел доступ к stop_event
    # в случае немедленной команды на остановку после запуска.
    try:
        CURRENT_STATE["stop_event"] = stop_event
        # Задачи будут добавлены после их создания ниже
        system_logger.debug(f"trade_main ({profile.SYMBOL}): stop_event зарегистрирован в CURRENT_STATE.")
    except Exception as e:
        # Это критическая ошибка, если CURRENT_STATE недоступен или не работает как ожидается
        system_logger.critical(f"trade_main ({profile.SYMBOL}): НЕ УДАЛОСЬ зарегистрировать stop_event в CURRENT_STATE: {e}", exc_info=True)
        # Возможно, стоит остановить дальнейшее выполнение, если CURRENT_STATE не работает
        return


    try:
        # Запускаем задачу прослушивания цен от Binance
        listener_task = asyncio.create_task(
            listen_klines(profile.SYMBOL, profile.TIMEFRAME, price_queue, stop_event)
        )
        # Запускаем задачу обработки цен и принятия торговых решений
        processor_task = asyncio.create_task(
            price_processor(price_queue, profile)
        )

        # --- Обновление CURRENT_STATE с задачами ---
        # Это должно быть сделано после успешного создания задач
        CURRENT_STATE["listener_task"] = listener_task
        CURRENT_STATE["processor_task"] = processor_task
        # CURRENT_STATE["main_task"] будет ссылаться на задачу, выполняющую trade_main_for_telegram,
        # и устанавливается в control_center.start_trading
        system_logger.debug(f"trade_main ({profile.SYMBOL}): listener_task и processor_task зарегистрированы в CURRENT_STATE.")

        # Ожидаем завершения обеих задач.
        # Если одна из них упадет с ошибкой (не CancelledError), gather пробросит эту ошибку.
        # Если одна из них будет отменена, gather также может быть отменен или выдать CancelledError.
        await asyncio.gather(listener_task, processor_task)
        
        # Если gather завершился без исключений, значит, обе задачи завершились штатно.
        # Это может произойти, если listen_klines и price_processor сами решат завершиться 
        # (например, по stop_event или по внутренней логике), что обычно не так для долгоживущих задач.
        system_logger.info(f"trade_main ({profile.SYMBOL}): asyncio.gather завершен штатно (обе задачи завершились сами по себе).")

    except asyncio.CancelledError:
        # Этот блок выполняется, если сама задача trade_main была отменена
        # (например, из control_center.stop_trading, который отменяет main_task)
        system_logger.info(f"trade_main ({profile.SYMBOL}): Задача отменена (asyncio.CancelledError). Инициируем остановку компонентов.")
        
        # Устанавливаем stop_event, чтобы сигнализировать listen_klines (и его потоку) о необходимости остановиться,
        # если отмена пришла не через stop_event (например, прямая отмена main_task).
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({profile.SYMBOL}): Установка stop_event из-за CancelledError.")
            stop_event.set()
        
        # Отменяем дочерние задачи, если они еще существуют и не завершены.
        # listen_klines должна сама обработать свою отмену и корректно завершить поток.
        # price_processor также должен обработать свою отмену.
        system_logger.info(f"trade_main ({profile.SYMBOL}): Отмена дочерних задач (listener, processor) после отмены trade_main...")
        if listener_task and not listener_task.done():
            listener_task.cancel()
        if processor_task and not processor_task.done():
            processor_task.cancel()
        
        # Ожидаем фактического завершения дочерних задач.
        # return_exceptions=True, чтобы gather не упал, если дочерняя задача при отмене выдаст ошибку,
        # отличную от CancelledError, или если сама CancelledError не была "поглощена" внутри дочерней задачи.
        if listener_task or processor_task: # Только если задачи были созданы
            tasks_to_await_on_cancel = [t for t in [listener_task, processor_task] if t]
            await asyncio.gather(*tasks_to_await_on_cancel, return_exceptions=True)
            system_logger.info(f"trade_main ({profile.SYMBOL}): Дочерние задачи собраны после отмены trade_main.")
        # Не пробрасываем CancelledError дальше, так как мы его обработали.
        # control_center, отменивший main_task, увидит, что main_task завершилась.
            
    except Exception as e:
        # Ловим любые другие неожиданные ошибки в trade_main
        system_logger.error(f"trade_main ({profile.SYMBOL}): Непредвиденная ошибка: {e}", exc_info=True)
        # При любой ошибке также пытаемся корректно остановить компоненты
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({profile.SYMBOL}): Установка stop_event из-за непредвиденной ошибки.")
            stop_event.set()
        
        system_logger.info(f"trade_main ({profile.SYMBOL}): Отмена дочерних задач (listener, processor) из-за непредвиденной ошибки...")
        if listener_task and not listener_task.done():
            listener_task.cancel()
        if processor_task and not processor_task.done():
            processor_task.cancel()

        if listener_task or processor_task:
            tasks_to_await_on_error = [t for t in [listener_task, processor_task] if t]
            await asyncio.gather(*tasks_to_await_on_error, return_exceptions=True)
            system_logger.info(f"trade_main ({profile.SYMBOL}): Дочерние задачи собраны после непредвиденной ошибки в trade_main.")
        # Можно решить, пробрасывать ли эту ошибку 'e' дальше, или считать, что trade_main завершилась (аварийно).
        # Для простоты пока не пробрасываем.
            
    finally:
        # Блок finally выполняется всегда, независимо от того, было исключение или нет.
        system_logger.info(f"trade_main ({profile.SYMBOL}): Блок finally. Гарантируем установку stop_event, если он еще не установлен.")
        
        # Убеждаемся, что stop_event точно установлен, чтобы все зависимые компоненты знали о завершении.
        if not stop_event.is_set():
            system_logger.warning(f"trade_main ({profile.SYMBOL}): stop_event не был установлен к моменту finally. Устанавливаем принудительно.")
            stop_event.set()
            # Если stop_event был установлен здесь, и listener_task еще не завершился, 
            # ему может потребоваться время на реакцию. Но listener_task уже должен быть отменен или завершен 
            # на предыдущих этапах (в try или except).
            # Если listener_task все еще жив, и мы только что установили stop_event,
            # нужно дать ему шанс завершиться. Это усложняет finally.
            # Лучше полагаться на то, что stop_event и отмена задач были сделаны в try/except.

        # Очистка ссылок на задачи и stop_event из CURRENT_STATE должна происходить
        # в bot_control.control_center.stop_trading() ПОСЛЕ того, как main_task (выполняющая trade_main)
        # полностью завершится. Здесь этого делать не нужно.

        system_logger.info(f"trade_main ({profile.SYMBOL}): Функция полностью завершена.")


async def trade_main_for_telegram(profile_name: str):
    """
    Обёртка для вызова trade_main из Telegram хендлеров.
    Загружает профиль и вызывает trade_main.
    """
    # system_logger здесь будет доступен через импорт из utils.logger
    system_logger.info(f"trade_main_for_telegram: Загрузка профиля '{profile_name}'...")
    try:
        profile_dict = get_profile_by_name(profile_name) # Эта функция должна быть доступна
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
        system_logger.info(f"trade_main_for_telegram: Профиль '{profile_name}' загружен. Вызов trade_main.")
        await trade_main(profile) # Передаем объект профиля
    except FileNotFoundError as e:
        system_logger.error(f"trade_main_for_telegram: Профиль '{profile_name}' не найден: {e}")
        # Здесь можно отправить уведомление в Telegram об ошибке
        # from utils.notifier import send_telegram_message # Пример
        # await send_telegram_message(f"Ошибка: Профиль '{profile_name}' не найден.")
    except Exception as e:
        system_logger.error(f"trade_main_for_telegram: Ошибка при выполнении для профиля '{profile_name}': {e}", exc_info=True)
        # Также можно отправить уведомление
        # await send_telegram_message(f"Критическая ошибка для профиля '{profile_name}'. Подробности в логе.")


# В блоке if __name__ == "__main__":
if __name__ == "__main__":
    # ... (код для выбора профиля или получения из sys.argv) ...
    # Пример для запуска с аргументом:
    if len(sys.argv) == 2:
        profile_name_arg = sys.argv[1]
        system_logger.info(f"Запуск из __main__ для профиля: {profile_name_arg}")
        try:
            profile_dict_main = get_profile_by_name(profile_name_arg)
            profile_main_obj = SimpleNamespace(**{k.upper(): v for k, v in profile_dict_main.items()})
            asyncio.run(trade_main(profile_main_obj))
        except FileNotFoundError:
            system_logger.error(f"Профиль '{profile_name_arg}' не найден при запуске из __main__.")
            print(f"❌ Профиль '{profile_name_arg}' не найден.")
        except KeyboardInterrupt:
            system_logger.info("Программа run_trading_stream.py прервана пользователем (KeyboardInterrupt) из __main__.")
        except Exception as e:
            system_logger.error(f"Непредвиденная ошибка в __main__: {e}", exc_info=True)
        finally:
            system_logger.info("Программа run_trading_stream.py (__main__) завершает работу.")
            logging.shutdown() # Важно для корректного закрытия лог-файлов
    else:
        # ... (твой код для интерактивного меню, если он здесь) ...
        print("Для прямого запуска укажите имя профиля: python run_trading_stream.py <имя_профиля>")







  



