# services/trade_logic.py

import numpy as np
from services.binance_client import client # Предполагается, что client настроен и импортируется
from services.technical_indicators import calculate_rsi, calculate_macd, calculate_ema, IndicatorCalculationError
from utils.logger import trading_logger, system_logger # Импортируем оба логгера

# Эту функцию теперь будет вызывать price_processor ОДИН РАЗ для инициализации истории
def get_initial_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> np.ndarray:
    """
    Загружает начальную историю цен (OHLCV) для инициализации.
    Возвращает numpy массив цен закрытия или пустой массив в случае ошибки.
    """
    try:
        # Используем system_logger для логирования системных операций, таких как API запросы
        system_logger.info(f"get_initial_ohlcv: Запрос {limit} свечей для {symbol} ({timeframe})...")
        klines = client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
        if not klines:
            system_logger.warning(f"get_initial_ohlcv ({symbol}): Не получено данных klines от API.")
            return np.array([])
        
        # Извлекаем цены закрытия (индекс 4 в стандартном ответе Binance API для klines)
        close_prices = np.array([float(kline[4]) for kline in klines])
        system_logger.info(f"get_initial_ohlcv ({symbol}): Получено {len(close_prices)} цен закрытия.")
        return close_prices
    except Exception as e:
        # Логируем ошибку получения данных через system_logger, так как это проблема с внешним сервисом
        system_logger.error(f"get_initial_ohlcv ({symbol}): Ошибка при получении OHLCV от Binance API: {e}", exc_info=True)
        return np.array([])

def check_buy_sell_signals(
    profile: object,                  # Объект профиля с настройками
    price_history_np: np.ndarray,     # Numpy массив с историей цен закрытия для расчета индикаторов
    current_close_price: float        # Самая последняя цена закрытия свечи из WebSocket
) -> str:
    """
    Анализирует исторические данные и текущую цену для генерации торговых сигналов.
    Не делает API-запросов, работает с переданными данными.
    Логирует значения индикаторов и итоговое решение в trading_logger.
    """
    symbol = profile.SYMBOL
    # trading_logger.debug(f"check_buy_sell_signals ({symbol}): Вход с price_history_np (size: {price_history_np.size}), current_close_price: {current_close_price}")

    # Извлекаем параметры из профиля с использованием getattr для безопасности и значений по умолчанию
    rsi_period = int(getattr(profile, "RSI_PERIOD", 14))
    rsi_overbought = float(getattr(profile, "RSI_OVERBOUGHT", 70.0))
    rsi_oversold = float(getattr(profile, "RSI_OVERSOLD", 30.0))
    macd_fast_period = int(getattr(profile, "MACD_FAST_PERIOD", 12))
    macd_slow_period = int(getattr(profile, "MACD_SLOW_PERIOD", 26))
    macd_signal_period = int(getattr(profile, "MACD_SIGNAL_PERIOD", 9))
    use_ema_filter = getattr(profile, "USE_EMA_FILTER", False) # Более явное имя для фильтра
    ema_filter_period = int(getattr(profile, "EMA_FILTER_PERIOD", 50)) # Более явное имя
    
    # Флаги использования индикаторов (по умолчанию True, если не заданы, но лучше задавать в профиле)
    use_rsi_indicator = getattr(profile, "USE_RSI", True)
    use_macd_indicator = getattr(profile, "USE_MACD", True)
    
    # Флаги для использования MACD в комбинации с RSI (по умолчанию False)
    use_macd_for_buy_confirmation = getattr(profile, "USE_MACD_FOR_BUY_CONFIRMATION", False) 
    use_macd_for_sell_confirmation = getattr(profile, "USE_MACD_FOR_SELL_CONFIRMATION", False)

    # --- Проверка достаточности данных для расчетов ---
    min_required_data_points = 1 # Минимум одна цена нужна всегда (current_close_price)
    if use_rsi_indicator:
        min_required_data_points = max(min_required_data_points, rsi_period + 1) # RSI обычно требует N+1 точек
    if use_macd_indicator:
        # MACD требует достаточно данных для самой медленной EMA + периода сигнальной линии
        min_required_data_points = max(min_required_data_points, macd_slow_period + macd_signal_period) 
    if use_ema_filter:
        min_required_data_points = max(min_required_data_points, ema_filter_period)
    
    if price_history_np.size < min_required_data_points:
        trading_logger.warning(f"Торг. логика ({symbol}): Недостаточно исторических данных ({price_history_np.size} из мин. {min_required_data_points}) для расчета индикаторов. Сигнал: 'hold'.")
        return 'hold'

    # --- Инициализация переменных для значений индикаторов ---
    rsi_value = np.nan 
    macd_line_value = np.nan
    signal_line_value = np.nan
    ema_filter_value = np.nan

    active_indicators_log = [] # Собираем информацию об активных индикаторах для лога

    # --- Расчет RSI ---
    if use_rsi_indicator:
        try:
            rsi_calculated_array = calculate_rsi(price_history_np, rsi_period)
            if rsi_calculated_array.size > 0:
                rsi_value = rsi_calculated_array[-1]
                active_indicators_log.append(f"RSI({rsi_period}): {rsi_value:.2f}")
            else:
                trading_logger.warning(f"Торг. логика ({symbol}): calculate_rsi вернул пустой массив.")
                use_rsi_indicator = False # Отключаем для этой проверки
        except IndicatorCalculationError as e:
            trading_logger.error(f"Торг. логика ({symbol}): Ошибка расчета RSI: {e}")
            use_rsi_indicator = False
        except Exception as e: # Ловим другие возможные ошибки
            trading_logger.error(f"Торг. логика ({symbol}): Неожиданная ошибка при расчете RSI: {e}", exc_info=True)
            use_rsi_indicator = False # Отключаем при любой ошибке

    # --- Расчет MACD ---
    if use_macd_indicator:
        try:
            macd_calculated_array, signal_calculated_array = calculate_macd(
                price_history_np, macd_fast_period, macd_slow_period, macd_signal_period
            )
            if macd_calculated_array.size > 0 and signal_calculated_array.size > 0:
                macd_line_value = macd_calculated_array[-1]
                signal_line_value = signal_calculated_array[-1]
                active_indicators_log.append(f"MACD({macd_fast_period},{macd_slow_period},{macd_signal_period}): {macd_line_value:.6f}/{signal_line_value:.6f}")
            else:
                trading_logger.warning(f"Торг. логика ({symbol}): calculate_macd вернул пустые массивы.")
                use_macd_indicator = False
        except IndicatorCalculationError as e:
            trading_logger.error(f"Торг. логика ({symbol}): Ошибка расчета MACD: {e}")
            use_macd_indicator = False
        except Exception as e:
            trading_logger.error(f"Торг. логика ({symbol}): Неожиданная ошибка при расчете MACD: {e}", exc_info=True)
            use_macd_indicator = False

    # --- Расчет EMA для фильтра ---
    if use_ema_filter:
        try:
            ema_calculated_array = calculate_ema(price_history_np, ema_filter_period)
            if ema_calculated_array.size > 0:
                ema_filter_value = ema_calculated_array[-1]
                active_indicators_log.append(f"EMA({ema_filter_period}): {ema_filter_value:.6f}")
            else:
                trading_logger.warning(f"Торг. логика ({symbol}): calculate_ema для фильтра вернул пустой массив.")
                use_ema_filter = False 
        except IndicatorCalculationError as e:
            trading_logger.error(f"Торг. логика ({symbol}): Ошибка расчета EMA для фильтра: {e}")
            use_ema_filter = False
        except Exception as e:
            trading_logger.error(f"Торг. логика ({symbol}): Неожиданная ошибка при расчете EMA для фильтра: {e}", exc_info=True)
            use_ema_filter = False
            
    # --- Логика принятия торговых решений ---
    buy_decision = False
    sell_decision = False

    # Сигнал на покупку
    if use_rsi_indicator and not np.isnan(rsi_value) and rsi_value < rsi_oversold:
        if use_macd_indicator and use_macd_for_buy_confirmation and not (np.isnan(macd_line_value) or np.isnan(signal_line_value)):
            if macd_line_value > signal_line_value: # MACD пересек сигнальную снизу вверх (бычий сигнал)
                buy_decision = True
        elif not use_macd_for_buy_confirmation: # Если подтверждение MACD не требуется
            buy_decision = True
    
    # Сигнал на продажу
    if use_rsi_indicator and not np.isnan(rsi_value) and rsi_value > rsi_overbought:
        if use_macd_indicator and use_macd_for_sell_confirmation and not (np.isnan(macd_line_value) or np.isnan(signal_line_value)):
            if macd_line_value < signal_line_value: # MACD пересек сигнальную сверху вниз (медвежий сигнал)
                sell_decision = True
        elif not use_macd_for_sell_confirmation: # Если подтверждение MACD не требуется
            sell_decision = True

    # Применение EMA фильтра
    if use_ema_filter and not np.isnan(ema_filter_value):
        if buy_decision and current_close_price < ema_filter_value:
            trading_logger.debug(f"Торг. логика ({symbol}): Сигнал ПОКУПКИ отменен фильтром EMA. Цена {current_close_price:.6f} < EMA({ema_filter_period}) {ema_filter_value:.6f}")
            buy_decision = False
        if sell_decision and current_close_price > ema_filter_value:
            trading_logger.debug(f"Торг. логика ({symbol}): Сигнал ПРОДАЖИ отменен фильтром EMA. Цена {current_close_price:.6f} > EMA({ema_filter_period}) {ema_filter_value:.6f}")
            sell_decision = False
        
    # --- Формирование итогового сообщения и возврат решения ---
    log_prefix = f"Профиль {symbol}: "
    log_indicators_part = ", ".join(active_indicators_log) if active_indicators_log else "Индикаторы неактивны/ошибка"
    log_price_part = f"Цена: {current_close_price:.6f}"
    
    final_log_message = f"{log_prefix}{log_indicators_part}, {log_price_part}"

    if buy_decision:
        final_log_message += " → СИГНАЛ НА ПОКУПКУ"
        trading_logger.info(final_log_message)
        # print(final_log_message) # Для отладки в консоли, можно будет убрать
        return 'buy'
    elif sell_decision:
        final_log_message += " → СИГНАЛ НА ПРОДАЖУ"
        trading_logger.info(final_log_message)
        # print(final_log_message) # Для отладки в консоли
        return 'sell'
    else:
        final_log_message += " → нет сигнала"
        # Логируем "нет сигнала" тоже на уровне INFO, чтобы видеть, что проверка прошла
        trading_logger.info(final_log_message) 
        # print(final_log_message) # Можно не печатать "нет сигнала" в консоль, чтобы не спамить
        return 'hold'