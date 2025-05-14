# services/trade_logic.py
import numpy as np
# Импортируем функции расчета индикаторов и ошибку
from services.technical_indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_ema,
    IndicatorCalculationError
)
from utils.logger import trading_logger # Логгер для торговых операций

# Минимальное количество свечей, необходимое для корректного расчета большинства индикаторов.
# Это значение должно быть немного больше, чем самый длинный период используемого индикатора + период сглаживания.
# Например, для MACD(12,26,9) нужно ~35 свечей (26+9). Для EMA(50) - 50 свечей.
# Если используется несколько, ориентируемся на самый "длинный".
# Это значение используется в run_trading_stream.py для get_initial_ohlcv и price_processor.
# Здесь оно приведено для информации и может использоваться для внутренних проверок, если необходимо.
MIN_CANDLES_REQUIRED_BY_LOGIC = 50


def get_initial_ohlcv(symbol: str, timeframe: str, limit: int) -> np.ndarray:
    """
    Загружает начальный набор исторических данных (OHLCV) для символа.
    Эта функция вызывается один раз при старте price_processor для инициализации истории цен.

    Args:
        symbol (str): Торговый символ.
        timeframe (str): Таймфрейм (например, '1m', '5m').
        limit (int): Количество свечей для загрузки.

    Returns:
        np.ndarray: Массив NumPy с ценами закрытия. Пустой массив в случае ошибки.
    """
    from services.binance_client import client # Импорт здесь, чтобы избежать циклических зависимостей на уровне модуля
    trading_logger.info(f"TradeLogic ({symbol}): Запрос начальных {limit} OHLCV данных для {symbol} ({timeframe})...")
    try:
        # klines: list of lists (timestamp, open, high, low, close, volume, ...)
        klines = client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
        # Нас интересуют только цены закрытия (индекс 4 в каждом подсписке kline)
        if not klines:
            trading_logger.warning(f"TradeLogic ({symbol}): Получен пустой список klines от API.")
            return np.array([])
            
        close_prices = np.array([float(kline[4]) for kline in klines])
        trading_logger.info(f"TradeLogic ({symbol}): Успешно загружено {len(close_prices)} цен закрытия.")
        return close_prices
    except Exception as e:
        trading_logger.error(f"TradeLogic ({symbol}): Ошибка при получении OHLCV: {e}", exc_info=True)
        return np.array([])


def check_buy_sell_signals(profile: object, historic_prices_np_array: np.ndarray, current_close_price: float) -> str:
    """
    Анализирует исторические данные и текущую цену для генерации торгового сигнала.

    Args:
        profile (SimpleNamespace): Объект профиля с настройками торговой пары и индикаторов.
        historic_prices_np_array (np.ndarray): Numpy массив исторических цен закрытия.
                                                Предполагается, что этот массив УЖЕ включает
                                                current_close_price как последний элемент, если индикаторы
                                                должны учитывать самую последнюю свечу для своего расчета.
        current_close_price (float): Самая последняя известная цена закрытия (из WebSocket).
                                     Эта цена используется для EMA фильтра и логирования.

    Returns:
        str: Торговый сигнал ('buy', 'sell', 'hold').
    """
    symbol = profile.SYMBOL
    
    # Параметры профиля для индикаторов
    rsi_period = int(getattr(profile, "RSI_PERIOD", 14))
    rsi_overbought = float(getattr(profile, "RSI_OVERBOUGHT", 70.0))
    rsi_oversold = float(getattr(profile, "RSI_OVERSOLD", 30.0))
    macd_fast_period = int(getattr(profile, "MACD_FAST_PERIOD", 12))
    macd_slow_period = int(getattr(profile, "MACD_SLOW_PERIOD", 26))
    macd_signal_period = int(getattr(profile, "MACD_SIGNAL_PERIOD", 9))
    
    # Флаги использования индикаторов из профиля
    use_rsi = bool(getattr(profile, "USE_RSI", True))
    use_macd = bool(getattr(profile, "USE_MACD", True))
    use_ema = bool(getattr(profile, "USE_EMA", False))
    ema_period = int(getattr(profile, "EMA_PERIOD", 50))

    # Флаги использования MACD для подтверждения сигналов RSI
    use_macd_for_buy = bool(getattr(profile, "USE_MACD_FOR_BUY", False))
    use_macd_for_sell = bool(getattr(profile, "USE_MACD_FOR_SELL", False))
    
    prices_for_indicators = historic_prices_np_array

    # Проверяем, достаточно ли у нас данных для расчета индикаторов
    # MIN_CANDLES_REQUIRED_BY_LOGIC - это константа, определенная в этом модуле.
    # Лучше, чтобы `run_trading_stream.price_processor` сам контролировал минимальное количество
    # свечей перед вызовом этой функции, чтобы не делать лишних вычислений.
    # Но дополнительная проверка здесь не помешает.
    if prices_for_indicators.size < MIN_CANDLES_REQUIRED_BY_LOGIC:
        trading_logger.debug(
            f"Signal Check ({symbol}): Not enough price data to calculate indicators in check_buy_sell_signals. "
            f"Have {prices_for_indicators.size}, need at least {MIN_CANDLES_REQUIRED_BY_LOGIC}. Holding."
        )
        return 'hold'

    # Инициализируем переменные для индикаторов
    rsi_values = np.array([])
    macd_line = np.array([])
    macd_signal_line = np.array([])
    ema_values = np.array([])

    # Расчет индикаторов
    try:
        if use_rsi:
            rsi_values = calculate_rsi(prices_for_indicators, rsi_period)
            # trading_logger.debug(f"Signal Check ({symbol}): Calculated RSI[-1]: {rsi_values[-1]:.2f}" if rsi_values.size > 0 else f"Signal Check ({symbol}): RSI calculation resulted in empty/short array")
        
        if use_macd:
            macd_line, macd_signal_line = calculate_macd(prices_for_indicators, macd_fast_period, macd_slow_period, macd_signal_period)
            # if macd_line.size > 0 and macd_signal_line.size > 0:
            #     trading_logger.debug(f"Signal Check ({symbol}): Calculated MACD[-1]: {macd_line[-1]:.6f}, Signal[-1]: {macd_signal_line[-1]:.6f}")
            # else:
            #     trading_logger.debug(f"Signal Check ({symbol}): MACD calculation resulted in empty/short arrays")

        if use_ema:
            ema_values = calculate_ema(prices_for_indicators, ema_period)
            # trading_logger.debug(f"Signal Check ({symbol}): Calculated EMA({ema_period})[-1]: {ema_values[-1]:.6f}" if ema_values.size > 0 else f"Signal Check ({symbol}): EMA calculation resulted in empty/short array")

    except IndicatorCalculationError as e:
        trading_logger.error(f"Signal Check ({symbol}): Error calculating indicators: {e}")
        return 'hold' 
    except Exception as e: 
        trading_logger.error(f"Signal Check ({symbol}): Unexpected error during indicator calculation: {e}", exc_info=True)
        return 'hold'

    # Получаем последние значения индикаторов
    last_rsi = rsi_values[-1] if use_rsi and rsi_values.size > 0 and not np.isnan(rsi_values[-1]) else None
    last_macd = macd_line[-1] if use_macd and macd_line.size > 0 and not np.isnan(macd_line[-1]) else None
    last_macd_signal = macd_signal_line[-1] if use_macd and macd_signal_line.size > 0 and not np.isnan(macd_signal_line[-1]) else None
    last_ema = ema_values[-1] if use_ema and ema_values.size > 0 and not np.isnan(ema_values[-1]) else None
    
    # --- Логика принятия решений ---
    buy_signal_triggered = False # Флаг для итогового решения о покупке
    sell_signal_triggered = False # Флаг для итогового решения о продаже

    # Условия для RSI
    rsi_gives_buy_signal = use_rsi and last_rsi is not None and last_rsi < rsi_oversold
    rsi_gives_sell_signal = use_rsi and last_rsi is not None and last_rsi > rsi_overbought

    # Условия для MACD (пересечение)
    macd_gives_buy_signal = use_macd and last_macd is not None and last_macd_signal is not None and last_macd > last_macd_signal
    macd_gives_sell_signal = use_macd and last_macd is not None and last_macd_signal is not None and last_macd < last_macd_signal

    # --- Определение сигнала на покупку ---
    if use_rsi: 
        if use_macd_for_buy and use_macd: 
            if rsi_gives_buy_signal and macd_gives_buy_signal:
                buy_signal_triggered = True
        elif rsi_gives_buy_signal: 
            buy_signal_triggered = True
    elif use_macd_for_buy and use_macd: # Если RSI не используется, но MACD для покупки используется
        if macd_gives_buy_signal:
            buy_signal_triggered = True
            
    # --- Определение сигнала на продажу ---
    if use_rsi: 
        if use_macd_for_sell and use_macd: 
            if rsi_gives_sell_signal and macd_gives_sell_signal:
                sell_signal_triggered = True
        elif rsi_gives_sell_signal: 
            sell_signal_triggered = True
    elif use_macd_for_sell and use_macd: # Если RSI не используется, но MACD для продажи используется
         if macd_gives_sell_signal:
            sell_signal_triggered = True
            
    # --- EMA Фильтр (если включен) ---
    if use_ema and last_ema is not None:
        if buy_signal_triggered and current_close_price < last_ema:
            trading_logger.info(
                f"Signal Check ({symbol}): BUY signal from indicators IGNORED due to EMA filter. "
                f"Price {current_close_price:.6f} < EMA({ema_period}) {last_ema:.6f}"
            )
            buy_signal_triggered = False 
        
        if sell_signal_triggered and current_close_price > last_ema:
            trading_logger.info(
                f"Signal Check ({symbol}): SELL signal from indicators IGNORED due to EMA filter. "
                f"Price {current_close_price:.6f} > EMA({ema_period}) {last_ema:.6f}"
            )
            sell_signal_triggered = False

    # --- Формирование и логирование итогового сообщения и сигнала ---
    log_message_parts = [f"Signal Eval ({symbol}): Price={current_close_price:.6f}"]
    if use_rsi:
        rsi_val_str = f"{last_rsi:.2f}" if last_rsi is not None else "N/A"
        log_message_parts.append(f"RSI({rsi_period})={rsi_val_str} (OB:{rsi_overbought},OS:{rsi_oversold})")
    if use_macd:
        macd_val_str = f"{last_macd:.6f}" if last_macd is not None else "N/A"
        signal_val_str = f"{last_macd_signal:.6f}" if last_macd_signal is not None else "N/A"
        log_message_parts.append(f"MACD({macd_fast_period},{macd_slow_period},{macd_signal_period})={macd_val_str},Signal={signal_val_str}")
    if use_ema:
        ema_val_str = f"{last_ema:.6f}" if last_ema is not None else "N/A"
        log_message_parts.append(f"EMA({ema_period})={ema_val_str}")

    if buy_signal_triggered:
        log_message_parts.append("-> Decision: BUY")
        trading_logger.info(" | ".join(log_message_parts))
        return 'buy'
    elif sell_signal_triggered:
        log_message_parts.append("-> Decision: SELL")
        trading_logger.info(" | ".join(log_message_parts))
        return 'sell'
    else:
        log_message_parts.append("-> Decision: HOLD")
        trading_logger.info(" | ".join(log_message_parts))
        return 'hold'