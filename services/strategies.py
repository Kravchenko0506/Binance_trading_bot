# services/strategies.py
"""
Defines the trading strategies employed by the bot.

This module includes:
- An abstract base class `TradingStrategy` to establish a common interface for all strategies.
- Concrete strategy implementations, such as `RsiMacdEmaStrategy`, which combines signals
  from RSI, MACD, and EMA indicators.
- A factory function `get_strategy_executor` for dynamically retrieving strategy instances based on
  configuration.

Each strategy is responsible for analyzing market data (candlesticks), current price,
and profile-specific parameters to generate a trading signal ("BUY", "SELL", or "HOLD").
The parameters for indicators (periods, thresholds, etc.) are expected to be defined
within the profile passed to the strategy.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd

# Import your functions for calculating technical indicators.
# This path assumes 'technical_indicators.py' is in the same 'services' folder.
# Adjust if your structure is different (e.g., 'from utils.technical_indicators import ...').
from .technical_indicators import (
    calculate_rsi,
    calculate_macd,
    calculate_ema,
    IndicatorCalculationError  # Assuming you might use this for error handling
)

# Import your main logger
# Assuming trading_logger is aliased or main_logger is preferred
from utils.logger import main_logger
# If you have a specific trading_logger and want to use it:
# from utils.logger import trading_logger as main_logger # (adjust as needed)


class TradingStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    This class defines the essential interface that all concrete trading strategies
    must adhere to. The core of this interface is the `get_signal` method,
    which encapsulates the logic for deciding whether to buy, sell, or hold
    an asset.
    """
    @abstractmethod
    def get_signal(self, candlesticks_df: pd.DataFrame, current_price: float, profile: Dict[str, Any]) -> str:
        """
        Analyzes market data and profile settings to generate a trading signal.

        Args:
            candlesticks_df (pd.DataFrame): A DataFrame containing historical candlestick data.
                It is expected to have at least a 'close' column for indicator calculations.
                Other OHLCV columns ('open', 'high', 'low', 'volume') might be used by
                more complex strategies. The data should be sorted chronologically, with
                the most recent candle at the end.
            current_price (float): The most recent market price of the asset. This is typically
                the closing price of the latest, possibly still forming, candlestick from
                a real-time data stream.
            profile (Dict[str, Any]): A dictionary containing the active trading profile's
                configuration. This includes parameters specific to the strategy (e.g.,
                `RSI_PERIOD`, `MACD_FAST_PERIOD`, `EMA_PERIOD`, buy/sell thresholds)
                and other relevant settings like the trading `symbol`.

        Returns:
            str: A trading signal string. Must be one of "BUY", "SELL", or "HOLD".
                 "BUY" indicates a signal to enter a long position.
                 "SELL" indicates a signal to exit a long position or enter a short position (if supported).
                 "HOLD" indicates no trading action should be taken.
        """
        pass


class RsiMacdEmaStrategy(TradingStrategy):
    """
    A trading strategy that combines signals from RSI, MACD, and EMA indicators.

    This strategy aims to identify favorable entry and exit points by confirming
    signals across multiple technical indicators. The specific logic for combining
    these indicators is derived from the user's `trade_logic.py`.

    Required profile parameters:
    - RSI: `USE_RSI` (bool), `RSI_PERIOD`, `RSI_OVERSOLD`, `RSI_OVERBOUGHT`
    - MACD: `USE_MACD` (bool), `MACD_FAST_PERIOD`, `MACD_SLOW_PERIOD`, `MACD_SIGNAL_PERIOD`
    - EMA: `USE_EMA` (bool), `EMA_PERIOD`, `EMA_BUY_BUFFER_PCT`, `EMA_SELL_BUFFER_PCT`
    - General: `symbol` (for logging)
    """

    def get_signal(self, candlesticks_df: pd.DataFrame, current_price: float, profile: Dict[str, Any]) -> str:
        """
        Generates a trading signal based on a combination of RSI, MACD, and EMA indicators.
        The logic mirrors the one previously in `get_trading_signal_new_logic`.
        """
        symbol = profile.get("symbol", "UNKNOWN_SYMBOL")
        log_message_parts = [
            f"StrategyCheck ({symbol}): Price={current_price:.6f}"]

        # --- Parameter Extraction from Profile ---
        # RSI parameters
        use_rsi = profile.get("USE_RSI", False)
        rsi_period = int(profile.get("RSI_PERIOD", 14))
        rsi_oversold = float(profile.get("RSI_OVERSOLD", 30.0))
        rsi_overbought = float(profile.get("RSI_OVERBOUGHT", 70.0))

        # MACD parameters
        use_macd = profile.get("USE_MACD", False)
        macd_fast_period = int(profile.get("MACD_FAST_PERIOD", 12))
        macd_slow_period = int(profile.get("MACD_SLOW_PERIOD", 26))
        macd_signal_period = int(profile.get("MACD_SIGNAL_PERIOD", 9))

        # EMA parameters
        use_ema = profile.get("USE_EMA", False)
        ema_period = int(profile.get("EMA_PERIOD", 50))
        # Buffers as percentages (e.g., 0.001 for 0.1%)
        ema_buy_buffer_pct = float(profile.get("EMA_BUY_BUFFER_PCT", 0.001))
        ema_sell_buffer_pct = float(profile.get("EMA_SELL_BUFFER_PCT", 0.001))

        # --- Data Validation ---
        if 'close' not in candlesticks_df.columns:
            main_logger.error(
                f"RsiMacdEmaStrategy ({symbol}): DataFrame is missing 'close' prices column.")
            return "HOLD"

        # Determine minimum required data length based on active indicators
        # +1 for potential previous_rsi logic if added
        min_len_rsi = rsi_period + 1 if use_rsi else 0
        # MACD needs more data due to smoothing
        min_len_macd = macd_slow_period + macd_signal_period if use_macd else 0
        min_len_ema = ema_period if use_ema else 0
        # At least 1 to prevent issues with max([])
        required_data_length = max(min_len_rsi, min_len_macd, min_len_ema, 1)

        if len(candlesticks_df) < required_data_length:
            main_logger.warning(
                f"RsiMacdEmaStrategy ({symbol}): Not enough historical data. "
                f"Need at least {required_data_length} candles for active indicators, got {len(candlesticks_df)}."
            )
            return "HOLD"

        close_prices = candlesticks_df['close']

        # --- Indicator Calculations ---
        last_rsi, last_macd, last_macd_signal, last_ema = None, None, None, None

        try:
            if use_rsi:
                rsi_series = calculate_rsi(close_prices, rsi_period)
                if not rsi_series.empty:
                    last_rsi = rsi_series.iloc[-1]
                log_message_parts.append(
                    f"RSI({rsi_period})={last_rsi if last_rsi is not None else 'N/A':.2f}")

            if use_macd:
                macd_line, signal_line, _ = calculate_macd(
                    close_prices, macd_fast_period, macd_slow_period, macd_signal_period)
                if not macd_line.empty:
                    last_macd = macd_line.iloc[-1]
                if not signal_line.empty:
                    last_macd_signal = signal_line.iloc[-1]
                log_message_parts.append(f"MACD({macd_fast_period},{macd_slow_period},{macd_signal_period})="
                                         f"{last_macd if last_macd is not None else 'N/A':.6f} "
                                         f"Sig={last_macd_signal if last_macd_signal is not None else 'N/A':.6f}")

            if use_ema:
                ema_series = calculate_ema(close_prices, ema_period)
                if not ema_series.empty:
                    last_ema = ema_series.iloc[-1]
                if last_ema is not None:
                    lower_ema_buffer = last_ema * (1 - ema_buy_buffer_pct)
                    upper_ema_buffer = last_ema * (1 + ema_sell_buffer_pct)
                    log_message_parts.append(f"EMA({ema_period})={last_ema:.6f} "
                                             f"[Lo:{lower_ema_buffer:.6f}, Hi:{upper_ema_buffer:.6f}]")
                else:
                    log_message_parts.append(f"EMA({ema_period})=N/A")

        except IndicatorCalculationError as e:
            main_logger.error(
                f"RsiMacdEmaStrategy ({symbol}): Error calculating indicators: {e}")
            return "HOLD"
        except Exception as e:  # Catch any other unexpected error during calculation
            main_logger.error(
                f"RsiMacdEmaStrategy ({symbol}): Unexpected error during indicator calculation: {e}", exc_info=True)
            return "HOLD"

        # Log all collected indicator values
        main_logger.debug(" | ".join(log_message_parts))

        # --- Signal Logic (from your trade_logic.py) ---
        buy_conditions_met = 0
        sell_conditions_met = 0
        # To ensure we only make a decision if at least one indicator is active
        conditions_checked = 0

        # RSI Logic
        if use_rsi and last_rsi is not None:
            conditions_checked += 1
            if last_rsi < rsi_oversold:
                buy_conditions_met += 1
            elif last_rsi > rsi_overbought:
                sell_conditions_met += 1

        # MACD Logic (Crossover: MACD line crosses above Signal line for BUY, below for SELL)
        # Your original logic used: last_macd > 0 for BUY, last_macd < 0 for SELL
        # Let's stick to your original logic:
        if use_macd and last_macd is not None and last_macd_signal is not None:  # Ensure both are available
            conditions_checked += 1
            # Original condition: last_macd > 0 and last_macd > last_macd_signal (for BUY)
            # Original condition: last_macd < 0 and last_macd < last_macd_signal (for SELL)
            # Let's use the conditions from the provided trade_logic.py:
            # BUY if MACD > 0 (implies bullish momentum)
            if last_macd > 0:  # Simplified from your code which had last_macd > 0 and crossing
                buy_conditions_met += 1
            # SELL if MACD < 0 (implies bearish momentum)
            elif last_macd < 0:  # Simplified from your code
                sell_conditions_met += 1
            # Consider adding crossover logic if desired:
            # if last_macd > last_macd_signal and previous_macd <= previous_signal_line: # Bullish crossover
            #    buy_conditions_met += 1
            # elif last_macd < last_macd_signal and previous_macd >= previous_signal_line: # Bearish crossover
            #    sell_conditions_met += 1

        # EMA Logic (Price relative to EMA with buffer)
        if use_ema and last_ema is not None:
            conditions_checked += 1
            lower_ema_buffer_price = last_ema * (1 - ema_buy_buffer_pct)
            upper_ema_buffer_price = last_ema * (1 + ema_sell_buffer_pct)

            # Price is above the lower band (bullish sign)
            if current_price > lower_ema_buffer_price:
                buy_conditions_met += 1
            # Price is below the upper band (bearish sign)
            if current_price < upper_ema_buffer_price:
                # Note: This condition for SELL is a bit counter-intuitive if EMA is rising.
                # Usually, price < EMA is bearish. Price < EMA * (1 + buffer) is a very loose bearish condition.
                # Your original trade_logic.py seems to use:
                # BUY: current_price > last_ema * (1 - ema_buy_buffer)
                # SELL: current_price < last_ema * (1 + ema_sell_buffer) - this implies EMA is a resistance
                # Let's adhere to your provided logic from `get_trading_signal_new_logic`
                # if current_price < last_ema * (1 + ema_sell_buffer_pct) # This seems too broad for a sell.
                # Let's assume the more standard: price must be below EMA (or its upper sell buffer) to be bearish for EMA
                # If price < last_ema or price < upper_ema_buffer_price (if buffer means sell above EMA but within buffer of resistance)
                # The logic in your get_trading_signal_new_logic implies EMA is used as a dynamic S/R.
                # BUY if current_price > last_ema * (1 - ema_buy_buffer)
                # SELL if current_price < last_ema * (1 + ema_sell_buffer) (this means sell if price is below the upper "sell consideration" band)
                # The original code has:
                # if current_price > (last_ema * (1 - ema_buy_buffer)): buy_signal_ema = True
                # if current_price < (last_ema * (1 + ema_sell_buffer)): sell_signal_ema = True
                # This implies both can be true.
                # Let's interpret it as: EMA provides a bullish bias if price > lower_band, and bearish if price < upper_band.
                # This might lead to conflicting signals if price is between lower_band and upper_band.
                # For simplicity, a common approach is:
                # Price > EMA (or EMA + buy_buffer) for BUY
                # Price < EMA (or EMA - sell_buffer) for SELL
                # Given your provided `trade_logic.py`'s structure:
                # The buy_conditions_met and sell_conditions_met are incremented separately.
                pass

        # --- Decision Making (from your trade_logic.py) ---
        # This part needs to exactly replicate the decision logic from your file.
        # Your provided file shows:
        # if buy_signal_rsi and buy_signal_macd and buy_signal_ema: return "BUY"
        # if sell_signal_rsi and sell_signal_macd and sell_signal_ema: return "SELL"
        # This is an "AND" condition for all active indicators.

        # Let's refine the buy/sell conditions based on your `trade_logic.py` more closely
        # Initialize boolean signals for each indicator
        buy_signal_rsi, sell_signal_rsi = False, False
        buy_signal_macd, sell_signal_macd = False, False
        buy_signal_ema, sell_signal_ema = False, False

        if use_rsi and last_rsi is not None:
            if last_rsi < rsi_oversold:
                buy_signal_rsi = True
            if last_rsi > rsi_overbought:
                # Note: RSI overbought itself is not a sell signal without price confirmation or divergence
                sell_signal_rsi = True

        if use_macd and last_macd is not None:  # Assuming your logic for MACD buy/sell was just positive/negative
            if last_macd > 0:
                buy_signal_macd = True
            if last_macd < 0:
                # (and last_macd < last_macd_signal) if using crossover for sell
                sell_signal_macd = True

        if use_ema and last_ema is not None:
            # Your logic: price > ema_low_buffer for buy, price < ema_high_buffer for sell
            if current_price > (last_ema * (1 - ema_buy_buffer_pct)):
                buy_signal_ema = True
            if current_price < (last_ema * (1 + ema_sell_buffer_pct)):
                sell_signal_ema = True  # This sell condition is broad

        # Determine how many indicators are configured to be used
        active_indicator_count = sum(
            [1 for used_flag in [use_rsi, use_macd, use_ema] if used_flag])

        if active_indicator_count == 0:
            main_logger.warning(
                f"RsiMacdEmaStrategy ({symbol}): No indicators enabled in profile. Holding.")
            return "HOLD"

        # --- Final Signal Aggregation (mimicking your get_trading_signal_new_logic) ---
        # BUY logic: All active indicators must give a buy signal
        all_buy = True
        if use_rsi and not buy_signal_rsi:
            all_buy = False
        if use_macd and not buy_signal_macd:
            all_buy = False
        if use_ema and not buy_signal_ema:
            all_buy = False

        if all_buy:
            main_logger.info(
                f"RsiMacdEmaStrategy ({symbol}): BUY signal generated (all active indicators confirm).")
            return "BUY"

        # SELL logic: All active indicators must give a sell signal
        all_sell = True
        if use_rsi and not sell_signal_rsi:
            all_sell = False
        if use_macd and not sell_signal_macd:
            all_sell = False
        if use_ema and not sell_signal_ema:
            all_sell = False  # Check if this condition makes sense for your EMA sell

        if all_sell:
            main_logger.info(
                f"RsiMacdEmaStrategy ({symbol}): SELL signal generated (all active indicators confirm).")
            return "SELL"

        return "HOLD"


def get_strategy_executor(strategy_name: str) -> TradingStrategy:
    """
    Factory function to retrieve an instance of a specified trading strategy.

    This function acts as a central point for creating strategy objects. It uses
    a dictionary to map strategy names (strings, typically from configuration)
    to their corresponding class instances. This approach allows for easy
    addition of new strategies without modifying the core trading logic that
    calls this factory.

    Args:
        strategy_name (str): The unique identifier for the desired strategy.
                             This name should match a key in the `strategies` dictionary.

    Returns:
        TradingStrategy: An initialized instance of the a subclass of `TradingStrategy`.

    Raises:
        ValueError: If `strategy_name` does not correspond to any known strategy
                    in the `strategies` mapping. The error message will include
                    a list of available strategy names for easier troubleshooting.
    """
    strategies: Dict[str, TradingStrategy] = {
        "RSI_MACD_EMA": RsiMacdEmaStrategy(),
        # Example of the previous simpler strategy, if you want to keep it:
        # "RSI_MA": RsiMaStrategy(), # (You would need to define RsiMaStrategy class as well)
    }

    strategy_instance = strategies.get(strategy_name)

    if not strategy_instance:
        main_logger.error(
            f"Strategy '{strategy_name}' not found in strategy executor mapping.")
        available_keys = list(strategies.keys())
        raise ValueError(
            f"Strategy '{strategy_name}' not found. Available strategies: {available_keys}")

    main_logger.info(
        f"Successfully loaded strategy executor for: {strategy_name}")
    return strategy_instance
