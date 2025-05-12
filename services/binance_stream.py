# services/binance_stream.py
import json
import threading # Модуль для работы с потоками (для _listen_thread)
import asyncio # Модуль для асинхронного программирования (для listen_klines и очереди)
import time    # Для организации задержек при переподключении
import websocket # Библиотека для работы с WebSocket (убедись, что установлен websocket-client)

# system_logger импортируется из централизованного модуля utils.logger
# Это позволяет управлять конфигурацией логирования в одном месте.
from utils.logger import system_logger

def _listen_thread(
    symbol: str,
    interval: str,
    price_queue: asyncio.Queue, # Очередь для передачи цен закрытия в асинхронный код
    async_loop: asyncio.AbstractEventLoop, # Цикл событий asyncio, в котором работает price_queue
    stop_event_local: threading.Event # Локальный экземпляр события для управления остановкой этого конкретного потока
):
    """
    Целевая функция, выполняемая в отдельном потоке (_thread).
    Ее задачи:
    1. Подключаться к WebSocket стриму Binance для указанной торговой пары и интервала.
    2. Слушать сообщения о новых kline (свечах).
    3. При закрытии свечи извлекать цену закрытия.
    4. Помещать цену закрытия в потокобезопасную очередь (price_queue), чтобы ее мог обработать асинхронный код.
    5. Корректно завершать свою работу при установке stop_event_local.
    6. Реализовывать базовую логику автоматического переподключения в случае обрыва связи или ошибок.
    """
    websocket_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
    websocket_connection = None # Переменная для хранения объекта WebSocket соединения

    # Параметры для логики переподключения
    initial_reconnect_delay_sec = 5  # Начальная задержка перед переподключением
    current_reconnect_delay_sec = initial_reconnect_delay_sec # Текущая задержка, может увеличиваться

    # Основной цикл работы потока. Он будет продолжаться, пока не будет установлен stop_event_local.
    # Этот внешний цикл также отвечает за логику переподключения.
    system_logger.info(f"WebSocket ({symbol}): Поток _listen_thread запущен.")
    while not stop_event_local.is_set():
        try:
            system_logger.info(f"WebSocket ({symbol}): Попытка подключения к {websocket_url}...")
            # Устанавливаем таймаут на операцию создания соединения (10 секунд)
            websocket_connection = websocket.create_connection(websocket_url, timeout=10)
            system_logger.info(f"WebSocket ({symbol}): Успешно подключено к {websocket_url}.")
            # После успешного подключения сбрасываем задержку переподключения к начальной
            current_reconnect_delay_sec = initial_reconnect_delay_sec
            
            # Устанавливаем таймаут на операции чтения (recv) с сокета (1 секунда).
            # Это критически важно: ws.recv() не должен блокировать поток навечно.
            # Таймаут позволяет регулярно проверять stop_event_local.is_set() в цикле.
            websocket_connection.settimeout(1.0)

            # Внутренний цикл: чтение сообщений из активного WebSocket соединения.
            # Продолжается, пока не установлен stop_event_local.
            while not stop_event_local.is_set():
                try:
                    # Пытаемся получить сообщение из WebSocket
                    message = websocket_connection.recv()
                    
                    if not message: # Некоторые реализации WebSocket могут вернуть пустую строку при таймауте
                        # system_logger.debug(f"WebSocket ({symbol}): получено пустое сообщение (возможно, recv таймаут без исключения).")
                        continue # Возвращаемся к началу внутреннего цикла для проверки stop_event_local

                    # Декодируем полученное JSON-сообщение
                    data_payload = json.loads(message)
                    kline_data = data_payload.get("k", {}) # Извлекаем данные свечи (ключ 'k')
                    
                    # Проверяем, является ли эта свеча закрытой ('x': True)
                    if kline_data.get("x"):
                        closing_price = float(kline_data["c"]) # 'c' - цена закрытия
                        # Потокобезопасно помещаем цену закрытия в очередь asyncio.
                        # Это позволяет передать данные из этого потока в асинхронный код (price_processor).
                        asyncio.run_coroutine_threadsafe(price_queue.put(closing_price), async_loop)
                        system_logger.debug(f"WebSocket ({symbol}): Цена закрытия {closing_price} отправлена в очередь.")

                except websocket.WebSocketTimeoutException:
                    # Это ожидаемое исключение из-за websocket_connection.settimeout(1.0).
                    # Оно означает, что за 1 секунду новых сообщений не пришло.
                    # Ничего страшного, просто продолжаем внутренний цикл, чтобы снова проверить stop_event_local.
                    # system_logger.debug(f"WebSocket ({symbol}): таймаут при чтении (ws.recv()), продолжаем...")
                    continue
                except websocket.WebSocketConnectionClosedException as e:
                    # Это исключение возникает, если соединение было закрыто удаленной стороной (Binance).
                    system_logger.warning(f"WebSocket ({symbol}): Соединение закрыто Binance: {e}. Попытка переподключения...")
                    break # Выходим из внутреннего цикла, чтобы инициировать переподключение во внешнем цикле.
                except json.JSONDecodeError as e:
                    # Ошибка при декодировании JSON. Возможно, пришло поврежденное сообщение.
                    message_preview = message[:100] if 'message' in locals() and isinstance(message, str) else "N/A"
                    system_logger.error(f"WebSocket ({symbol}): Ошибка декодирования JSON: {e}. Сообщение (начало): '{message_preview}'")
                    # Продолжаем пытаться читать сообщения, это могла быть единичная проблема.
                    continue
                except Exception as e:
                    # Ловим другие возможные ошибки внутри цикла чтения сообщений.
                    if stop_event_local.is_set():
                        # Если дана команда на остановку, эта ошибка может быть связана с процессом закрытия соединения.
                        system_logger.info(f"WebSocket ({symbol}): Ошибка при чтении во время процесса остановки: {e}")
                    else:
                        # Если это неожиданная ошибка, логируем ее подробно.
                        system_logger.error(f"WebSocket ({symbol}): Непредвиденная ошибка в цикле чтения (_listen_thread): {e}", exc_info=True)
                    break # Выходим из внутреннего цикла. Если stop_event_local не установлен, будет попытка переподключения.

            # Если мы вышли из внутреннего цикла (например, из-за WebSocketConnectionClosedException или другой ошибки),
            # но stop_event_local еще не установлен, значит, внешний цикл попытается переподключиться.
            # Перед этим нужно закрыть текущее соединение, если оно еще существует.
            if websocket_connection:
                websocket_connection.close()
                system_logger.info(f"WebSocket ({symbol}): Соединение websocket_connection закрыто (внутренний цикл завершен).")
                websocket_connection = None # Сбрасываем, чтобы избежать повторного закрытия в блоке finally внешнего цикла.

        except websocket.WebSocketException as e: # Ошибки, связанные с библиотекой WebSocket (например, при create_connection)
            if stop_event_local.is_set():
                system_logger.info(f"WebSocket ({symbol}): Ошибка подключения WebSocket во время процесса остановки: {e}")
                # Если дана команда на остановку, нет смысла пытаться переподключаться.
                break # Выходим из внешнего цикла (while not stop_event_local.is_set())
            system_logger.error(f"WebSocket ({symbol}): Ошибка подключения WebSocket (например, create_connection не удалось): {e}.")
            # Не делаем break здесь, чтобы внешний цикл сделал задержку и попробовал переподключиться.
        except Exception as e:
            # Ловим любые другие неожиданные ошибки на уровне установки соединения или во внешнем цикле.
            if stop_event_local.is_set():
                system_logger.info(f"WebSocket ({symbol}): Непредвиденная ошибка во внешнем цикле во время процесса остановки: {e}")
                break # Выходим из внешнего цикла, если дана команда на остановку.
            system_logger.error(f"WebSocket ({symbol}): Непредвиденная ошибка во внешнем цикле _listen_thread: {e}", exc_info=True)
            # Аналогично, не делаем break, чтобы внешний цикл попытался переподключиться.
        
        finally:
            # Блок finally для try внутри внешнего цикла.
            # Гарантирует закрытие соединения, если оно по какой-то причине осталось открытым
            # и мы вышли из блока try (например, из-за исключения, которое не привело к break из внешнего цикла).
            if websocket_connection and websocket_connection.connected:
                websocket_connection.close()
                system_logger.info(f"WebSocket ({symbol}): Соединение websocket_connection принудительно закрыто в блоке finally внешнего цикла.")
                websocket_connection = None # Сбрасываем после закрытия

        # Если stop_event_local все еще не установлен (т.е. мы здесь из-за ошибки, а не команды на остановку),
        # делаем задержку перед следующей попыткой подключения во внешнем цикле.
        if not stop_event_local.is_set():
            system_logger.info(f"WebSocket ({symbol}): Ожидание {current_reconnect_delay_sec} секунд перед следующей попыткой подключения...")
            # Реализуем прерываемую задержку: спим по 1 секунде, каждый раз проверяя stop_event_local.
            for _ in range(current_reconnect_delay_sec):
                if stop_event_local.is_set():
                    system_logger.info(f"WebSocket ({symbol}): Остановка задержки переподключения из-за установки stop_event_local.")
                    break # Прерываем задержку, если дана команда на остановку.
                time.sleep(1)
            # Здесь можно добавить логику для увеличения задержки при повторных неудачных попытках,
            # например, current_reconnect_delay_sec = min(current_reconnect_delay_sec * 2, 60) # Удваивать, но не более 60с.
        else:
            # Если stop_event_local был установлен во время выполнения блока try или задержки,
            # выходим из основного (внешнего) цикла потока.
            system_logger.info(f"WebSocket ({symbol}): Получен сигнал stop_event_local, внешний цикл _listen_thread завершается.")
            break 

    system_logger.info(f"WebSocket ({symbol}): Поток _listen_thread полностью завершен.")


async def listen_klines(
    symbol: str,
    interval: str,
    price_queue: asyncio.Queue,      # Очередь для передачи цен от _listen_thread
    stop_event_from_caller: threading.Event # Экземпляр threading.Event, переданный от вызывающей стороны (trade_main)
):
    """
    Асинхронная корутина-"менеджер" для WebSocket стрима.
    Ее задачи:
    1. Получить текущий цикл событий asyncio.
    2. Запустить функцию `_listen_thread` в отдельном потоке Python (`threading.Thread`).
    3. Передать `_listen_thread` необходимые аргументы, включая `price_queue` и `stop_event_from_caller`.
    4. "Жить" и оставаться активной, пока не будет установлен `stop_event_from_caller` или пока ее саму не отменят.
    5. При получении сигнала на остановку (через `stop_event_from_caller` или `asyncio.CancelledError`),
       гарантировать корректное завершение запущенного потока `_listen_thread`.
    """
    async_loop = asyncio.get_event_loop() # Получаем текущий цикл событий asyncio
    websocket_worker_thread = None         # Переменная для хранения объекта потока

    try:
        system_logger.info(f"listen_klines ({symbol}): Запуск фонового потока _listen_thread...")
        # Создаем объект потока.
        # daemon=False означает, что основной процесс Python будет ждать завершения этого потока,
        # если только не будет вызван sys.exit() или если join() не будет вызван/завершится.
        # Для управляемого завершения мы будем использовать join().
        websocket_worker_thread = threading.Thread(
            target=_listen_thread, # Функция, которую будет выполнять поток
            args=(symbol, interval, price_queue, async_loop, stop_event_from_caller), # Аргументы для _listen_thread
            daemon=False # Явное указание, что поток не является демоном
        )
        websocket_worker_thread.start() # Запускаем поток

        # Эта корутина (listen_klines) будет оставаться активной и периодически "просыпаться",
        # чтобы проверить, не установлен ли stop_event_from_caller и жив ли еще рабочий поток.
        # await asyncio.sleep(0.1) передает управление другим задачам asyncio, предотвращая блокировку.
        while not stop_event_from_caller.is_set() and websocket_worker_thread.is_alive():
            await asyncio.sleep(0.1)
        
        # Если мы вышли из цикла, анализируем причину:
        if stop_event_from_caller.is_set():
            system_logger.info(f"listen_klines ({symbol}): stop_event_from_caller установлен. Корутина готовится к завершению, ожидая поток.")
        elif not websocket_worker_thread.is_alive(): # Поток завершился сам по себе (возможно, из-за ошибки)
            system_logger.warning(f"listen_klines ({symbol}): Фоновый поток _listen_thread неожиданно завершился. Устанавливаем stop_event_from_caller.")
            if not stop_event_from_caller.is_set(): # Если еще не установлен, устанавливаем, чтобы другие части системы знали.
                 stop_event_from_caller.set()
        
    except asyncio.CancelledError:
        # Этот блок выполняется, если сама задача listen_klines была отменена
        # (например, из bot_control.control_center при остановке бота).
        system_logger.info(f"listen_klines ({symbol}): Задача отменена (получен asyncio.CancelledError).")
        # Важно сигнализировать фоновому потоку _listen_thread о необходимости остановиться,
        # если это еще не было сделано через stop_event_from_caller.
        if not stop_event_from_caller.is_set():
            system_logger.info(f"listen_klines ({symbol}): Установка stop_event_from_caller из-за CancelledError.")
            stop_event_from_caller.set()
        # Не нужно пробрасывать CancelledError дальше (re-raise), если мы хотим,
        # чтобы вызывающая корутина (например, trade_main) корректно обработала отмену этой задачи.
    except Exception as e:
        # Ловим любые другие непредвиденные ошибки в корутине listen_klines.
        system_logger.error(f"listen_klines ({symbol}): Непредвиденная ошибка в корутине: {e}", exc_info=True)
        # В случае любой ошибки также пытаемся корректно остановить фоновый поток.
        if not stop_event_from_caller.is_set():
            system_logger.info(f"listen_klines ({symbol}): Установка stop_event_from_caller из-за непредвиденной ошибки в корутине.")
            stop_event_from_caller.set()
    finally:
        # Блок finally выполняется всегда, независимо от того, как была завершена корутина (штатно или с ошибкой).
        # Его задача - гарантировать, что фоновый поток _listen_thread будет корректно остановлен и дождан.
        system_logger.info(f"listen_klines ({symbol}): Блок finally. Гарантируем установку stop_event_from_caller и ожидание завершения потока.")
        
        # Убеждаемся, что stop_event_from_caller точно установлен.
        if not stop_event_from_caller.is_set():
            # Эта ситуация не должна возникать при штатной отмене или ошибке, но для надежности.
            system_logger.warning(f"listen_klines ({symbol}): stop_event_from_caller не был установлен к моменту finally. Устанавливаем принудительно.")
            stop_event_from_caller.set()

        # Проверяем, был ли создан поток и жив ли он еще.
        if websocket_worker_thread and websocket_worker_thread.is_alive():
            system_logger.info(f"listen_klines ({symbol}): Ожидание (join) завершения фонового потока _listen_thread (таймаут 10 секунд)...")
            # Метод join() блокирует выполнение до тех пор, пока поток websocket_worker_thread не завершится,
            # или пока не истечет таймаут.
            websocket_worker_thread.join(timeout=10.0) 
            if websocket_worker_thread.is_alive():
                # Если поток все еще жив после таймаута, это указывает на проблему в _listen_thread
                # (например, он не реагирует на stop_event_from_caller или завис).
                system_logger.error(f"listen_klines ({symbol}): Фоновый поток _listen_thread НЕ ЗАВЕРШИЛСЯ за 10 секунд после вызова join! Возможна утечка ресурсов.")
            else:
                system_logger.info(f"listen_klines ({symbol}): Фоновый поток _listen_thread успешно завершен (joined).")
        elif websocket_worker_thread: # Если объект потока был создан, но поток уже не активен
            system_logger.info(f"listen_klines ({symbol}): Фоновый поток _listen_thread уже был завершен к моменту вызова join в finally.")
        else: # Если объект потока даже не был создан (например, из-за ошибки до thread.start())
            system_logger.info(f"listen_klines ({symbol}): Фоновый поток _listen_thread не был создан (websocket_worker_thread is None).")

        system_logger.info(f"listen_klines ({symbol}): Корутина-менеджер полностью завершена.")