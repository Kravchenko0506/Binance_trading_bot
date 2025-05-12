# bot_control/control_center.py
import asyncio
# Предполагается, что system_logger импортируется из твоего модуля utils.logger
from utils.logger import system_logger

# Глобальное состояние для отслеживания активных торговых сессий и их компонентов
CURRENT_STATE = {
    "running": False,        # Запущен ли какой-либо торговый профиль
    "profile_name": None,    # Имя активного профиля
    "main_task": None,       # Ссылка на asyncio.Task, выполняющую trade_main_for_telegram -> trade_main
    "listener_task": None,   # Ссылка на asyncio.Task для listen_klines (устанавливается из trade_main)
    "processor_task": None,  # Ссылка на asyncio.Task для price_processor (устанавливается из trade_main)
    "stop_event": None       # Экземпляр threading.Event для сигнализации остановки (устанавливается из trade_main)
}

def get_status():
    """Возвращает текущий статус работы бота."""
    # Можно добавить больше деталей, например, время последней свечи, P&L и т.д. в будущем
    return {
        "running": CURRENT_STATE["running"],
        "profile": CURRENT_STATE["profile_name"],
        "main_task_status": CURRENT_STATE["main_task"].done() if CURRENT_STATE["main_task"] else "N/A",
        "listener_task_status": CURRENT_STATE["listener_task"].done() if CURRENT_STATE["listener_task"] else "N/A",
        "processor_task_status": CURRENT_STATE["processor_task"].done() if CURRENT_STATE["processor_task"] else "N/A",
        "stop_event_is_set": CURRENT_STATE["stop_event"].is_set() if CURRENT_STATE["stop_event"] else "N/A",
    }

async def _internal_stop_logic(context_msg: str = ""):
    """
    Внутренняя логика для корректной остановки всех активных компонентов.
    context_msg: строка для логирования, указывающая, откуда был вызван stop.
    Возвращает True, если были предприняты действия по остановке.
    """
    activity_performed = False
    log_context = f" (контекст: {context_msg})" if context_msg else ""
    system_logger.info(f"control_center: Запуск _internal_stop_logic{log_context}...")

    # 1. Сигнализируем через threading.Event потоку _listen_thread о необходимости остановиться
    stop_event = CURRENT_STATE.get("stop_event")
    if stop_event and not stop_event.is_set():
        system_logger.info(f"control_center: Установка stop_event{log_context}...")
        stop_event.set()
        activity_performed = True
        # Даем небольшую паузу, чтобы поток _listen_thread и корутина listen_klines
        # могли отреагировать на установку stop_event перед отменой asyncio задач.
        await asyncio.sleep(0.2) 
    elif stop_event and stop_event.is_set():
        system_logger.info(f"control_center: stop_event уже был установлен{log_context}.")
        activity_performed = True # Считаем активностью, т.к. процесс остановки уже мог быть запущен

    # 2. Отменяем asyncio задачи (listener_task, processor_task, main_task)
    # Они должны быть спроектированы так, чтобы корректно обрабатывать CancelledError
    # и завершать свою работу (например, listen_klines должна дождаться своего потока).
    
    tasks_to_cancel_and_await = []
    # Порядок отмены может иметь значение. Обычно отменяют "сверху вниз" или "от зависимых к главным".
    # main_task -> (listener_task, processor_task)
    # Однако, listen_klines ждет stop_event, который мы уже установили.
    # Отмена main_task приведет к CancelledError в trade_main, которая также установит stop_event
    # и отменит listener/processor. Двойная отмена не страшна.

    # Собираем задачи для отмены и ожидания
    # Важно отменять задачи, которые еще не завершены (not task.done())
    for task_key in ["main_task", "listener_task", "processor_task"]: # Порядок может быть важен
        task = CURRENT_STATE.get(task_key)
        if task and not task.done():
            system_logger.info(f"control_center: Отмена задачи '{task_key}'{log_context}...")
            task.cancel()
            tasks_to_cancel_and_await.append(task)
            activity_performed = True
        elif task and task.done():
            system_logger.info(f"control_center: Задача '{task_key}'{log_context} уже была завершена.")
            # Если задача уже завершена, но stop_event не был установлен, это может быть индикатором проблемы
            if task_key == "listener_task" and stop_event and not stop_event.is_set():
                system_logger.warning(f"control_center: {task_key} завершена, но stop_event не установлен! Проверьте логи {task_key}.")


    if tasks_to_cancel_and_await:
        system_logger.info(f"control_center: Ожидание завершения {len(tasks_to_cancel_and_await)} отмененных задач{log_context}...")
        # Ожидаем фактического завершения всех отмененных задач.
        # return_exceptions=True позволяет gather завершиться, даже если одна из задач
        # при отмене выбросит исключение (отличное от CancelledError) или если сама CancelledError
        # не была корректно "поглощена" внутри задачи.
        results = await asyncio.gather(*tasks_to_cancel_and_await, return_exceptions=True)
        
        for i, result in enumerate(results):
            # Пытаемся получить имя задачи для более информативного лога
            # (Task.get_name() доступно с Python 3.8)
            task_obj = tasks_to_cancel_and_await[i]
            task_name_log = getattr(task_obj, 'get_name', lambda: f"Task_{i}")()


            if isinstance(result, asyncio.CancelledError):
                system_logger.info(f"control_center: Задача '{task_name_log}'{log_context} успешно отменена (вернула CancelledError).")
            elif isinstance(result, Exception): # Любое другое исключение
                system_logger.error(f"control_center: Задача '{task_name_log}'{log_context} завершилась с ошибкой при отмене или во время работы: {result!r}", exc_info=False) # exc_info=False если result уже исключение
            else: # Задача завершилась без исключения (возможно, вернула значение)
                system_logger.info(f"control_center: Задача '{task_name_log}'{log_context} завершилась с результатом: {result!r}")
        system_logger.info(f"control_center: Все указанные asyncio задачи собраны после отмены{log_context}.")
    elif activity_performed: # Если был установлен stop_event, но не было asyncio задач для отмены
        system_logger.info(f"control_center: stop_event был установлен{log_context}, но не было активных asyncio задач для отмены/ожидания.")
    else:
        system_logger.info(f"control_center: Не найдено активных компонентов для остановки{log_context}.")
        
    return activity_performed


async def start_trading(profile_name: str, trade_runner_coro_func): # trade_runner_coro_func это trade_main_for_telegram
    """
    Запускает торговую сессию для указанного профиля.
    trade_runner_coro_func - асинхронная функция (корутина), которая будет запущена (например, trade_main_for_telegram).
    """
    if CURRENT_STATE["running"]:
        msg = f"⚠️ Бот уже работает с профилем: {CURRENT_STATE['profile_name']}"
        system_logger.warning(f"control_center: Попытка запуска, когда бот уже работает ({CURRENT_STATE['profile_name']}).")
        return msg

    # Очищаем предыдущее состояние на случай, если что-то осталось от аварийного завершения
    # Это также остановит любые "зависшие" компоненты, если они есть
    system_logger.info(f"control_center: Вызов _internal_stop_logic перед запуском нового профиля '{profile_name}' для очистки...")
    await _internal_stop_logic(context_msg=f"очистка перед запуском {profile_name}")
    # Сбрасываем CURRENT_STATE после очистки, перед новым запуском
    for key in list(CURRENT_STATE.keys()): # list(keys()) для безопасного изменения словаря
        if key == "running":
            CURRENT_STATE[key] = False
        else:
            CURRENT_STATE[key] = None
    system_logger.info(f"control_center: CURRENT_STATE сброшен перед запуском нового профиля.")


    CURRENT_STATE["profile_name"] = profile_name
    CURRENT_STATE["running"] = True # Устанавливаем флаг running до создания задачи
    
    system_logger.info(f"control_center: Запуск trade_runner_coro_func для профиля '{profile_name}'...")
    # trade_runner_coro_func (т.е. trade_main_for_telegram) должна вызывать trade_main,
    # а trade_main уже сама создаст stop_event, listener_task, processor_task
    # и зарегистрирует их в CURRENT_STATE.
    main_task = asyncio.create_task(trade_runner_coro_func(profile_name))
    CURRENT_STATE["main_task"] = main_task # Сохраняем основную задачу
    
    # Небольшая пауза, чтобы дать время trade_main инициализироваться и заполнить 
    # stop_event, listener_task, processor_task в CURRENT_STATE.
    # Это может быть полезно, если команда stop_trading может быть вызвана очень быстро после start_trading.
    await asyncio.sleep(0.5) # 0.5 секунды должно быть достаточно для инициализации

    # Проверка, что компоненты действительно зарегистрировались (для отладки)
    if not CURRENT_STATE.get("stop_event") or not CURRENT_STATE.get("listener_task"):
        system_logger.warning(f"control_center: После запуска профиля '{profile_name}' stop_event или listener_task не были зарегистрированы в CURRENT_STATE! Это может привести к проблемам с остановкой.")
        # Можно добавить логику отката или ошибки, если это критично
        # await stop_trading() # Например, попытаться остановить, если что-то пошло не так
        # return f"❌ Ошибка инициализации компонентов для профиля {profile_name}. Торговля не запущена."


    msg = f"🚀 Торговля запущена по профилю: {profile_name}"
    system_logger.info(f"control_center: {msg}")
    return msg


async def stop_trading():
    """Останавливает текущую торговую сессию."""
    # Проверяем, есть ли что останавливать, более строго
    has_active_components = (
        CURRENT_STATE["running"] or
        CURRENT_STATE["main_task"] or
        CURRENT_STATE["listener_task"] or
        CURRENT_STATE["processor_task"] or
        CURRENT_STATE["stop_event"]
    )

    if not has_active_components:
        msg = "⛔️ Бот уже остановлен или не был запущен (нет активных компонентов)."
        system_logger.info(f"control_center: {msg}")
        # Сбросим флаг running на всякий случай, если он как-то остался True
        CURRENT_STATE["running"] = False
        CURRENT_STATE["profile_name"] = None # Также сбросим имя профиля
        return msg

    system_logger.info("control_center: Попытка остановить торговлю (вызов stop_trading)...")
    
    await _internal_stop_logic(context_msg="по команде stop_trading")

    # Сброс состояния CURRENT_STATE ПОСЛЕ того, как все компоненты были остановлены
    system_logger.info("control_center: Остановка завершена. Сброс CURRENT_STATE...")
    CURRENT_STATE["running"] = False
    CURRENT_STATE["profile_name"] = None
    CURRENT_STATE["main_task"] = None
    CURRENT_STATE["listener_task"] = None
    CURRENT_STATE["processor_task"] = None
    CURRENT_STATE["stop_event"] = None # Удаляем/сбрасываем stop_event
    
    msg = "🛑 Торговля успешно остановлена."
    system_logger.info(f"control_center: {msg}")
    return msg
