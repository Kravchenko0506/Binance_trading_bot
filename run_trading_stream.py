# run_trading_stream.py
import asyncio
import threading
from types import SimpleNamespace
import numpy as np # Для работы с массивами numpy
import collections # Для использования deque

# Импорты из твоего проекта
from config.profile_loader import get_profile_by_name # Предполагается, что он есть
from services.binance_stream import listen_klines
# Изменяем импорт get_ohlcv на get_initial_ohlcv
from services.trade_logic import check_buy_sell_signals, get_initial_ohlcv
from services.order_execution import place_order # Предполагается, что он есть
from utils.logger import system_logger, trading_logger # Импортируем оба логгера
from bot_control.control_center import CURRENT_STATE # Для регистрации компонентов

# Настройки для истории цен (можно вынести в config/settings.py или профиль)
PRICE_HISTORY_MAX_LEN = 250  # Максимальная длина истории цен для индикаторов (для MACD нужно ~50-100, для EMA может больше)
MIN_PRICE_HISTORY_FOR_TRADE = 50 # Минимальное количество свечей для начала расчетов (зависит от самого длинного периода индикатора)


async def price_processor(
    price_queue: asyncio.Queue,
    profile: SimpleNamespace,
    stop_event_ref: threading.Event # Ссылка на stop_event из trade_main для проверки перед длительными операциями
):
    """
    Асинхронно обрабатывает цены из очереди, обновляет историю цен,
    вызывает торговую логику и размещает ордера.
    """
    symbol = profile.SYMBOL
    timeframe = profile.TIMEFRAME
    system_logger.info(f"Price processor ({symbol}): ЗАПУЩЕН и ожидает инициализации истории цен.")

    # --- 1. Инициализация истории цен ---
    # Вызываем get_initial_ohlcv ОДИН РАЗ при старте price_processor
    initial_close_prices_np = get_initial_ohlcv(symbol, timeframe, limit=PRICE_HISTORY_MAX_LEN + 50) # Запрашиваем с запасом

    if initial_close_prices_np.size < MIN_PRICE_HISTORY_FOR_TRADE:
        system_logger.error(f"Price processor ({symbol}): Недостаточно начальных исторических данных ({initial_close_prices_np.size} из мин. {MIN_PRICE_HISTORY_FOR_TRADE}). Обработчик цен останавливается.")
        # Здесь нужно как-то сигнализировать об ошибке в trade_main, чтобы остановить всю сессию
        # Например, можно выбросить исключение, которое будет поймано в trade_main
        # Или использовать asyncio.Event для сигнализации об ошибке
        # Пока просто выходим, но это требует доработки для корректной остановки сессии.
        if not stop_event_ref.is_set(): # Если не останавливаемся штатно
             stop_event_ref.set() # Сигнализируем об остановке, т.к. дальше работать не можем
        return 

    # Используем deque для эффективного хранения скользящего окна цен
    # Заполняем deque начальными данными, обрезая до PRICE_HISTORY_MAX_LEN, если их больше.
    # Берем последние PRICE_HISTORY_MAX_LEN цен.
    price_history_deque = collections.deque(
        initial_close_prices_np[-(PRICE_HISTORY_MAX_LEN):], 
        maxlen=PRICE_HISTORY_MAX_LEN
    )
    system_logger.info(f"Price processor ({symbol}): Инициализирована история цен, {len(price_history_deque)} записей (maxlen={PRICE_HISTORY_MAX_LEN}).")

    try:
        # Основной цикл обработки цен из очереди
        while not stop_event_ref.is_set(): # Добавляем проверку stop_event_ref для более быстрой остановки
            try:
                # Ожидаем новую цену из очереди с таймаутом, чтобы не блокироваться вечно
                # и периодически проверять stop_event_ref.
                new_close_price = await asyncio.wait_for(price_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # system_logger.debug(f"Price processor ({symbol}): Таймаут ожидания цены из очереди. Проверяем stop_event...")
                if stop_event_ref.is_set(): # Если дана команда на остановку, выходим
                    break
                continue # Продолжаем цикл, если не останавливаемся

            system_logger.debug(f"Price processor ({symbol}): получена новая цена закрытия {new_close_price} из очереди.")

            # Обновляем историю: добавляем новую цену.
            # Если deque полон, самая старая цена автоматически удалится слева.
            price_history_deque.append(new_close_price)
            
            # Преобразуем deque в numpy array для передачи в функции расчета индикаторов.
            # Это делается на каждой итерации, т.к. индикаторы требуют numpy array.
            current_prices_np_for_indicators = np.array(price_history_deque)

            # Проверяем, достаточно ли у нас данных в истории ПОСЛЕ добавления новой цены
            if current_prices_np_for_indicators.size < MIN_PRICE_HISTORY_FOR_TRADE:
                trading_logger.info(f"Price processor ({symbol}): Накапливаем историю, {current_prices_np_for_indicators.size}/{MIN_PRICE_HISTORY_FOR_TRADE} цен. Сигналы не проверяются.")
                price_queue.task_done() # Не забываем подтверждать обработку элемента очереди
                continue

            # Вызываем check_buy_sell_signals с актуальной историей и последней ценой закрытия
            trading_action = check_buy_sell_signals(
                profile, 
                current_prices_np_for_indicators, 
                new_close_price # new_close_price - это самая актуальная цена для принятия решения
            ) 
            
            # Логируем принятое действие (если нужно дополнительно к логам из check_buy_sell_signals)
            # trading_logger.debug(f"Price processor ({symbol}): Действие от trade_logic: {trading_action}")

            if trading_action != 'hold':
                # Здесь логика размещения ордера
                system_logger.info(f"Price processor ({symbol}): Размещение ордера: {trading_action}")
                place_order(trading_action, profile.SYMBOL, profile.COMMISSION_RATE) # Убедись, что place_order корректно обрабатывает ошибки
            
            price_queue.task_done() # Сообщаем очереди, что элемент обработан

    except asyncio.CancelledError:
        system_logger.info(f"Price processor ({symbol}): Задача отменена (asyncio.CancelledError).")
    except Exception as e:
        system_logger.error(f"Price processor ({symbol}): Непредвиденная ошибка: {e}", exc_info=True)
        if not stop_event_ref.is_set(): # Если ошибка, а не штатная остановка
            stop_event_ref.set() # Сигнализируем об остановке всей сессии
    finally:
        system_logger.info(f"Price processor ({symbol}): Завершение работы.")


async def trade_main(profile: SimpleNamespace):
    """
    Основная асинхронная функция для управления торговой сессией одного профиля.
    """
    symbol = profile.SYMBOL
    system_logger.info(f"trade_main ({symbol}): Запуск торговой сессии для профиля.")
    
    # stop_event создается здесь и передается во все компоненты, которые должны на него реагировать
    stop_event = threading.Event()
    # Очередь для цен от listen_klines к price_processor
    price_queue = asyncio.Queue(maxsize=100) # Ограничиваем размер очереди
    
    listener_task = None
    processor_task = None

    # Регистрация stop_event в CURRENT_STATE для доступа из control_center
    # Это должно быть сделано как можно раньше
    try:
        if "stop_event" not in CURRENT_STATE or CURRENT_STATE["stop_event"] is None: # Предотвращаем перезапись, если уже есть (хотя не должно быть)
            CURRENT_STATE["stop_event"] = stop_event
            system_logger.debug(f"trade_main ({symbol}): stop_event зарегистрирован в CURRENT_STATE.")
        else:
            system_logger.warning(f"trade_main ({symbol}): stop_event уже был в CURRENT_STATE. Не перезаписан.")
            # Если stop_event уже есть, возможно, предыдущая сессия не была корректно очищена.
            # Устанавливаем текущий stop_event, чтобы новая сессия реагировала на него.
            if not CURRENT_STATE["stop_event"].is_set(): # Если старый не установлен, значит что-то не так
                 CURRENT_STATE["stop_event"].set() # Останавливаем старый, если он еще не остановлен
            CURRENT_STATE["stop_event"] = stop_event # Устанавливаем новый
            system_logger.info(f"trade_main ({symbol}): Перезаписан stop_event в CURRENT_STATE.")

    except Exception as e:
        system_logger.critical(f"trade_main ({symbol}): НЕ УДАЛОСЬ зарегистрировать stop_event в CURRENT_STATE: {e}", exc_info=True)
        # Если CURRENT_STATE не работает, дальнейшая работа невозможна
        return # Завершаем trade_main

    try:
        # Запускаем listen_klines для получения цен
        listener_task = asyncio.create_task(
            listen_klines(symbol, profile.TIMEFRAME, price_queue, stop_event)
        )
        # Запускаем price_processor для обработки цен и торговой логики
        processor_task = asyncio.create_task(
            price_processor(price_queue, profile, stop_event) # Передаем stop_event и в processor
        )

        # Обновляем CURRENT_STATE ссылками на созданные задачи
        CURRENT_STATE["listener_task"] = listener_task
        CURRENT_STATE["processor_task"] = processor_task
        system_logger.debug(f"trade_main ({symbol}): listener_task и processor_task зарегистрированы в CURRENT_STATE.")

        # Ожидаем завершения обеих задач (listen_klines и price_processor)
        # Они должны завершиться, когда будет установлен stop_event или если они сами упадут с ошибкой.
        await asyncio.gather(listener_task, processor_task)
        
        system_logger.info(f"trade_main ({symbol}): asyncio.gather(listener, processor) завершен.")

    except asyncio.CancelledError:
        system_logger.info(f"trade_main ({symbol}): Основная задача отменена (asyncio.CancelledError). Инициируем остановку компонентов.")
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({symbol}): Установка stop_event из-за CancelledError.")
            stop_event.set()
        
        # Отменяем дочерние задачи (хотя они должны среагировать на stop_event)
        if listener_task and not listener_task.done(): listener_task.cancel()
        if processor_task and not processor_task.done(): processor_task.cancel()
        
        if listener_task or processor_task:
            tasks_to_await = [t for t in [listener_task, processor_task] if t]
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
            system_logger.info(f"trade_main ({symbol}): Дочерние задачи собраны после отмены trade_main.")
            
    except Exception as e:
        system_logger.error(f"trade_main ({symbol}): Непредвиденная ошибка в основной торговой логике: {e}", exc_info=True)
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({symbol}): Установка stop_event из-за непредвиденной ошибки.")
            stop_event.set()
        
        if listener_task and not listener_task.done(): listener_task.cancel()
        if processor_task and not processor_task.done(): processor_task.cancel()

        if listener_task or processor_task:
            tasks_to_await = [t for t in [listener_task, processor_task] if t]
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
            system_logger.info(f"trade_main ({symbol}): Дочерние задачи собраны после непредвиденной ошибки.")
            
    finally:
        system_logger.info(f"trade_main ({symbol}): Блок finally. Гарантируем установку stop_event.")
        if not stop_event.is_set():
            system_logger.warning(f"trade_main ({symbol}): stop_event не был установлен к моменту finally. Устанавливаем принудительно.")
            stop_event.set()
        
        # Очистка CURRENT_STATE должна происходить в control_center.stop_trading
        system_logger.info(f"trade_main ({symbol}): Функция для профиля полностью завершена.")

# Функция-обертка для вызова из Telegram хендлеров
async def trade_main_for_telegram(profile_name: str):
    """Загружает профиль и запускает trade_main."""
    system_logger.info(f"trade_main_for_telegram: Загрузка профиля '{profile_name}'...")
    try:
        profile_dict = get_profile_by_name(profile_name)
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
        system_logger.info(f"trade_main_for_telegram: Профиль '{profile_name}' загружен. Вызов trade_main.")
        await trade_main(profile)
    except FileNotFoundError as e:
        system_logger.error(f"trade_main_for_telegram: Профиль '{profile_name}' не найден: {e}")
        # В идеале, здесь нужно вернуть информацию об ошибке, чтобы control_center мог ее обработать
        # или отправить уведомление в Telegram из notifier.py
    except Exception as e:
        system_logger.error(f"trade_main_for_telegram: Ошибка при выполнении для профиля '{profile_name}': {e}", exc_info=True)

# Код для прямого запуска run_trading_stream.py (если нужен)
if __name__ == "__main__":
    import sys
    import logging # для logging.shutdown()
    # ... (твой код для выбора профиля из sys.argv или интерактивного меню) ...
    # Пример:
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
            system_logger.error(f"Непредвиденная ошибка в __main__ (run_trading_stream.py): {e}", exc_info=True)
        finally:
            system_logger.info("Программа run_trading_stream.py (__main__) завершает работу.")
            if logging.getLogger().handlers: # Проверяем, есть ли еще обработчики
                 logging.shutdown()
    else:
        print("Для прямого запуска: python run_trading_stream.py <имя_профиля>")
        # Здесь может быть твой код для интерактивного меню, если он запускается отсюда







  



