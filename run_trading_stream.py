# run_trading_stream.py
import asyncio # Библиотека для асинхронного программирования
import threading # Для создания объекта threading.Event для управления остановкой
import sys # Для работы с аргументами командной строки (при прямом запуске) и sys.exit
import logging # Для вызова logging.shutdown()
from types import SimpleNamespace # Для удобного создания объектов из словарей (например, для профиля)
import numpy as np # Для работы с массивами цен, если это требуется индикаторами
import collections # Для использования collections.deque для эффективного хранения истории цен

# --- Импорты из твоего проекта ---

# Предполагается, что объект settings импортируется из config.settings
# и содержит флаги USE_STOP_LOSS, USE_TAKE_PROFIT, USE_MIN_PROFIT и др.
from config import settings

# Функции для проверки условий стоп-лосса, тейк-профита и достаточной прибыли.
# ВАЖНО: Эти функции должны быть адаптированы, чтобы принимать current_close_price как аргумент,
# а не делать собственные API-запросы для получения текущей цены.
from utils.profit_check import is_stop_loss_triggered, is_take_profit_reached, is_enough_profit
# Асинхронная функция для отправки уведомлений в Telegram
from utils.notifier import send_notification

# Загрузка конфигурации профиля по имени
from config.profile_loader import get_profile_by_name
# Асинхронная функция-менеджер для прослушивания WebSocket стрима Binance
from services.binance_stream import listen_klines
# Функции торговой логики: проверка сигналов по индикаторам и начальная загрузка истории цен
from services.trade_logic import check_buy_sell_signals, get_initial_ohlcv
# Функция для размещения ордеров на бирже (покупка/продажа)
from services.order_execution import place_order
# Централизованные логгеры: system_logger для системных событий, trading_logger для торговых операций
from utils.logger import system_logger, trading_logger
# Глобальное состояние для отслеживания активных задач и stop_event из control_center
from bot_control.control_center import CURRENT_STATE



# --- Константы для управления историей цен ---

# Максимальная длина истории цен (количество свечей), которую мы храним для расчета индикаторов.
# Это значение должно быть достаточным для самого "длинного" периода индикатора, который ты используешь.
# Например, если у тебя EMA с периодом 200, то PRICE_HISTORY_MAX_LEN должен быть не меньше 200.
PRICE_HISTORY_MAX_LEN = 250
# Минимальное количество свечей в истории, необходимое для начала расчетов индикаторов и принятия торговых решений.
# Это значение также зависит от периодов используемых индикаторов. Например, MACD(12,26,9) требует около 35+ свечей,
# RSI(14) требует около 15+. Устанавливается с запасом.
MIN_PRICE_HISTORY_FOR_TRADE = 50


async def execute_trade_action(
    action_type: str, # "buy" или "sell"
    symbol: str,
    profile: SimpleNamespace,
    reason_message: str # Сообщение-причина для лога и уведомления
):
    """
    Вспомогательная асинхронная функция для выполнения торгового действия (покупка/продажа),
    логирования этого действия и отправки уведомления.
    """
    # Логируем намерение совершить действие
    # trading_logger для торговых действий, system_logger для более общего контекста
    trading_logger.info(reason_message)
    system_logger.info(f"Price processor ({symbol}): Инициировано действие '{action_type}' по причине: {reason_message}")

    try:
        # Размещаем ордер на бирже.
        # ВАЖНО: Если place_order - это синхронная блокирующая функция (делает сетевой запрос),
        # ее вызов заблокирует весь asyncio event loop. В идеале, place_order должна быть
        # асинхронной (async def) и использовать await для сетевых операций,
        # либо вызываться через await asyncio.to_thread(place_order, ...) (для Python 3.9+)
        # или await loop.run_in_executor(None, place_order, ...).
        # Пока оставляем прямой вызов, предполагая, что он либо быстрый, либо ты это учтешь.
        await place_order(action_type, symbol, profile)
        
        # Отправляем уведомление в Telegram об успешном действии
        await send_notification(reason_message) # Уведомление содержит причину
        system_logger.info(f"Price processor ({symbol}): Уведомление об операции '{action_type}' отправлено.")
        return True # Действие успешно инициировано
    except Exception as e:
        system_logger.error(f"Price processor ({symbol}): Ошибка при размещении ордера '{action_type}': {e}", exc_info=True)
        # Уведомляем об ошибке ордера
        await send_notification(f"❌ Ошибка ордера '{action_type}' для {symbol}. Причина: {e}. Смотрите системные логи.")
        return False # Действие не удалось


async def check_and_handle_risk_conditions(
    symbol: str,
    profile: SimpleNamespace,
    current_price: float,
    strategy_has_issued_sell: bool
) -> bool:
    """
    Проверяет условия риск-менеджмента для продажи:
    1. Stop-loss
    2. Take-profit
    3. Минимальный профит (если стратегия не дала сигнал)
    
    Если какое-либо условие выполняется — происходит продажа, логирование и Telegram-уведомление.
    Возвращает True, если была продажа. Иначе — False.
    """

    from utils.position_manager import has_open_position

    # === Проверка: есть ли вообще открытая позиция ===
    # Если файл last_buy_price отсутствует, значит — позиции нет, продавать нечего
    # Это защищает от спама при срабатывании take-profit по уже закрытой позиции
    if not has_open_position(symbol):
        system_logger.debug(f"Risk Check: позиция по {symbol} уже закрыта — пропускаем проверку TP/SL/MinProfit.")
        return False

    # === 1. STOP-LOSS ===
    # Наивысший приоритет: продажа при достижении убытка
    if settings.USE_STOP_LOSS and is_stop_loss_triggered(symbol, current_price):
        reason = f"‼️ Stop-loss: {symbol} принудительно продается (цена {current_price:.6f}) из-за достижения уровня стоп-лосс."
        await execute_trade_action("sell", symbol, profile, reason)
        return True

    # === 2. TAKE-PROFIT ===
    # Второй по приоритету: продажа при достижении заданной прибыли
    if settings.USE_TAKE_PROFIT and is_take_profit_reached(symbol, current_price):
        reason = f"✅ Take-profit: {symbol} достиг цели прибыли (цена {current_price:.6f}). Принудительная продажа."
        await execute_trade_action("sell", symbol, profile, reason)
        return True

    # === 3. MIN-PROFIT ===
    # Только если стратегия НЕ дала сигнал `sell`
    if settings.USE_MIN_PROFIT and not strategy_has_issued_sell:
        if is_enough_profit(symbol, current_price):
            reason = f"💰 Минимальный профит: {symbol} продается (цена {current_price:.6f}) для фиксации прибыли без сигнала стратегии."
            await execute_trade_action("sell", symbol, profile, reason)
            return True
        # Ветка else логируется внутри is_enough_profit()

    # Если ни одно из условий не выполнено — ничего не делаем
    return False



async def price_processor(
    price_queue: asyncio.Queue,
    profile: SimpleNamespace,
    stop_event_ref: threading.Event
):
    """
    Асинхронно обрабатывает цены из очереди, обновляет историю цен,
    вызывает торговую логику (включая риск-менеджмент) и размещает ордера.
    """
    symbol = profile.SYMBOL
    timeframe = profile.TIMEFRAME
    system_logger.info(f"Price processor ({symbol}): ЗАПУЩЕН. Ожидание инициализации истории цен...")

    # --- 1. Инициализация истории цен ---
    try:
        initial_close_prices_np = get_initial_ohlcv(symbol, timeframe, limit=PRICE_HISTORY_MAX_LEN + 50)
    except Exception as e:
        system_logger.error(f"Price processor ({symbol}): Критическая ошибка при вызове get_initial_ohlcv: {e}", exc_info=True)
        if not stop_event_ref.is_set(): stop_event_ref.set()
        return

    if initial_close_prices_np.size < MIN_PRICE_HISTORY_FOR_TRADE:
        system_logger.error(f"Price processor ({symbol}): Недостаточно начальных исторических данных ({initial_close_prices_np.size} из мин. {MIN_PRICE_HISTORY_FOR_TRADE}). Обработчик цен останавливается.")
        if not stop_event_ref.is_set(): stop_event_ref.set()
        return 

    price_history_deque = collections.deque(
        initial_close_prices_np[-(PRICE_HISTORY_MAX_LEN):], 
        maxlen=PRICE_HISTORY_MAX_LEN
    )
    system_logger.info(f"Price processor ({symbol}): Инициализирована история цен, {len(price_history_deque)} записей (maxlen={PRICE_HISTORY_MAX_LEN}).")

    try:
        while not stop_event_ref.is_set():
            new_close_price = None
            try:
                new_close_price = await asyncio.wait_for(price_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if stop_event_ref.is_set(): break
                continue

            system_logger.debug(f"Price processor ({symbol}): Получена новая цена закрытия {new_close_price} из очереди.")
            price_history_deque.append(new_close_price)
            current_prices_np_for_indicators = np.array(price_history_deque)

            if current_prices_np_for_indicators.size < MIN_PRICE_HISTORY_FOR_TRADE:
                trading_logger.info(f"Price processor ({symbol}): Накапливаем историю, {current_prices_np_for_indicators.size}/{MIN_PRICE_HISTORY_FOR_TRADE} цен. Сигналы не проверяются.")
                price_queue.task_done()
                continue

            # --- Шаг 1: Проверки риск-менеджмента (Стоп-лосс, Тейк-профит) ---
            # Эти проверки имеют приоритет. strategy_has_issued_sell здесь False, т.к. основная стратегия еще не вызывалась.
            # Передаем new_close_price для актуальной проверки.
            risk_sell_executed = await check_and_handle_risk_conditions(symbol, profile, new_close_price, strategy_has_issued_sell=False)
            if risk_sell_executed:
                price_queue.task_done()
                continue # Позиция закрыта, переходим к следующей цене

            # --- Шаг 2: Основная торговая стратегия ---
            strategy_action = check_buy_sell_signals(
                profile, 
                current_prices_np_for_indicators, 
                new_close_price
            )
            
            action_taken_this_cycle = False
            if strategy_action == 'buy':
                # (Дополнительные проверки перед покупкой: есть ли уже позиция, достаточно ли баланса и т.д.)
                reason_msg_buy = f"📈 Стратегия ({symbol}) подала сигнал на ПОКУПКУ по цене {new_close_price:.6f}."
                # Логирование самого сигнала 'buy' происходит внутри check_buy_sell_signals
                # Здесь логируем намерение и результат place_order
                if await execute_trade_action("buy", symbol, profile, reason_msg_buy):
                    action_taken_this_cycle = True
            
            elif strategy_action == 'sell':
                # Логика продажи по сигналу стратегии
                proceed_with_strategy_sell = True
                # Опциональная проверка минимальной прибыли для ПРОДАЖИ по СТРАТЕГИИ
                if getattr(settings, "USE_MIN_PROFIT_FOR_STRATEGY_SELL", False): # Если такой флаг есть и True
                    if not is_enough_profit(symbol, new_close_price): # is_enough_profit сама логирует отмену
                        proceed_with_strategy_sell = False
                        trading_logger.info(f"Price processor ({symbol}): Продажа по стратегии отменена из-за недостаточной прибыли (согласно is_enough_profit).")
                
                if proceed_with_strategy_sell:
                    reason_msg_sell = f"📉 Стратегия ({symbol}) подала сигнал на ПРОДАЖУ по цене {new_close_price:.6f}."
                    if await execute_trade_action("sell", symbol, profile, reason_msg_sell):
                        action_taken_this_cycle = True

            # --- Шаг 3: Проверка минимального профита (если не было других действий) ---
            # Вызываем, только если стратегия сказала 'hold' (т.е. strategy_action == 'hold')
            # и не было других действий по риску или стратегии в этом цикле
            if not action_taken_this_cycle and strategy_action == 'hold':
                # Передаем strategy_has_issued_sell=False, так как стратегия не дала сигнал на продажу
                await check_and_handle_risk_conditions(symbol, profile, new_close_price, strategy_has_issued_sell=False)
                # Результат этой функции уже обработан внутри нее (если была продажа)
            
            price_queue.task_done()

    except asyncio.CancelledError:
        system_logger.info(f"Price processor ({symbol}): Задача отменена (asyncio.CancelledError).")
    except Exception as e:
        system_logger.error(f"Price processor ({symbol}): Непредвиденная ошибка: {e}", exc_info=True)
        if not stop_event_ref.is_set(): stop_event_ref.set()
    finally:
        system_logger.info(f"Price processor ({symbol}): Завершение работы.")


async def trade_main(profile: SimpleNamespace):
    """
    Основная асинхронная функция для управления торговой сессией одного профиля.
    Создает и управляет задачами listen_klines и price_processor.
    """
    symbol = profile.SYMBOL
    system_logger.info(f"trade_main ({symbol}): Запуск торговой сессии для профиля '{profile.SYMBOL}'.")
    
    stop_event = threading.Event()
    price_queue = asyncio.Queue(maxsize=100) 
    
    listener_task = None
    processor_task = None

    try:
        current_stop_event = CURRENT_STATE.get("stop_event")
        if current_stop_event is not None and not current_stop_event.is_set():
            system_logger.warning(f"trade_main ({symbol}): Обнаружен активный stop_event в CURRENT_STATE от предыдущей сессии. Попытка остановить старую сессию.")
            current_stop_event.set() 
            await asyncio.sleep(0.5) # Даем время на реакцию
        
        CURRENT_STATE["stop_event"] = stop_event
        system_logger.debug(f"trade_main ({symbol}): stop_event ({id(stop_event)}) зарегистрирован в CURRENT_STATE.")
    except Exception as e:
        system_logger.critical(f"trade_main ({symbol}): НЕ УДАЛОСЬ зарегистрировать stop_event в CURRENT_STATE: {e}", exc_info=True)
        return

    try:
        listener_task = asyncio.create_task(
            listen_klines(symbol, profile.TIMEFRAME, price_queue, stop_event)
        )
        processor_task = asyncio.create_task(
            price_processor(price_queue, profile, stop_event) 
        )

        CURRENT_STATE["listener_task"] = listener_task
        CURRENT_STATE["processor_task"] = processor_task
        system_logger.debug(f"trade_main ({symbol}): listener_task и processor_task зарегистрированы в CURRENT_STATE.")

        await asyncio.gather(listener_task, processor_task)
        system_logger.info(f"trade_main ({symbol}): asyncio.gather(listener, processor) завершен.")

    except asyncio.CancelledError:
        system_logger.info(f"trade_main ({symbol}): Основная задача отменена (asyncio.CancelledError). Инициируем остановку компонентов.")
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({symbol}): Установка stop_event из-за CancelledError в trade_main.")
            stop_event.set()
        
        tasks_to_cancel = [t for t in [listener_task, processor_task] if t and not t.done()]
        if tasks_to_cancel:
            for task in tasks_to_cancel: task.cancel()
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            system_logger.info(f"trade_main ({symbol}): Дочерние задачи собраны после отмены trade_main.")
            
    except Exception as e:
        system_logger.error(f"trade_main ({symbol}): Непредвиденная ошибка в основной торговой логике: {e}", exc_info=True)
        if not stop_event.is_set():
            system_logger.info(f"trade_main ({symbol}): Установка stop_event из-за непредвиденной ошибки.")
            stop_event.set()
        
        tasks_to_cancel_on_error = [t for t in [listener_task, processor_task] if t and not t.done()]
        if tasks_to_cancel_on_error:
            for task in tasks_to_cancel_on_error: task.cancel()
            await asyncio.gather(*tasks_to_cancel_on_error, return_exceptions=True)
            system_logger.info(f"trade_main ({symbol}): Дочерние задачи собраны после непредвиденной ошибки в trade_main.")
            
    finally:
        system_logger.info(f"trade_main ({symbol}): Блок finally. Гарантируем установку stop_event.")
        if not stop_event.is_set():
            system_logger.warning(f"trade_main ({symbol}): stop_event не был установлен к моменту finally. Устанавливаем принудительно.")
            stop_event.set()
        
        system_logger.info(f"trade_main ({symbol}): Функция для профиля '{symbol}' полностью завершена.")


async def trade_main_for_telegram(profile_name: str):
    """
    Асинхронная функция-обертка для запуска trade_main из Telegram хендлеров.
    """
    system_logger.info(f"trade_main_for_telegram: Загрузка профиля '{profile_name}'...")
    try:
        profile_dict = get_profile_by_name(profile_name)
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
        system_logger.info(f"trade_main_for_telegram: Профиль '{profile_name}' загружен. Вызов trade_main.")
        await trade_main(profile)
    except FileNotFoundError as e:
        system_logger.error(f"trade_main_for_telegram: Профиль '{profile_name}' не найден: {e}")
        await send_notification(f"❌ Ошибка запуска: Профиль '{profile_name}' не найден.")
    except Exception as e:
        system_logger.error(f"trade_main_for_telegram: Ошибка при выполнении для профиля '{profile_name}': {e}", exc_info=True)
        await send_notification(f"❌ Критическая ошибка для профиля '{profile_name}'. Подробности в системном логе.")

# Блок для прямого запуска (если нужен для отладки)
if __name__ == "__main__":
    if len(sys.argv) == 2:
        profile_name_arg = sys.argv[1]
        system_logger.info(f"run_trading_stream.py: Запуск из __main__ для профиля: {profile_name_arg}")
        try:
            profile_dict_main = get_profile_by_name(profile_name_arg)
            profile_main_obj = SimpleNamespace(**{k.upper(): v for k, v in profile_dict_main.items()})
            asyncio.run(trade_main(profile_main_obj))
        except FileNotFoundError:
            system_logger.error(f"run_trading_stream.py (__main__): Профиль '{profile_name_arg}' не найден.")
            print(f"❌ Профиль '{profile_name_arg}' не найден.")
        except KeyboardInterrupt:
            system_logger.info("run_trading_stream.py (__main__): Программа прервана пользователем (KeyboardInterrupt).")
        except Exception as e:
            system_logger.error(f"run_trading_stream.py (__main__): Непредвиденная ошибка: {e}", exc_info=True)
        finally:
            system_logger.info("run_trading_stream.py (__main__): Завершение работы.")
            if logging.getLogger().handlers: 
                 logging.shutdown()
    else:
        print("Для прямого запуска укажите имя профиля: python run_trading_stream.py <имя_профиля>")






  



