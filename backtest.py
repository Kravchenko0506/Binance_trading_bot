import argparse
import sys
import pandas as pd
import numpy as np
from datetime import datetime
from binance.client import Client
from types import SimpleNamespace
import pickle

from services.technical_indicators import apply_indicators
from services.trade_logic import check_buy_sell_signals
from utils.logger import setup_logger
from config.profile_loader import get_profile_by_name


def fetch_klines(symbol, interval, start_str, end_str):
    client = Client()
    
     #явное форматирование дат
    start_dt = datetime.strptime(start_str, "%d %b, %Y")
    end_dt = datetime.strptime(end_str, "%d %b, %Y")
    start_str = start_dt.strftime("%d %b %Y %H:%M:%S")
    end_str = end_dt.strftime("%d %b %Y %H:%M:%S")
    
    print(f"📡 Загрузка данных {symbol} [{interval}] с {start_str} по {end_str} ...")
    klines = client.get_historical_klines(symbol, interval, start_str, end_str)
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def run_backtest(df, profile):
    setup_logger()
    df = apply_indicators(df, profile)

    usdt = 100
    asset = 0
    last_buy_price = 0
    trades = 0

    for i in range(len(df)):
        row = df.iloc[i]
        profile.LAST_ROW = row
        signal = check_buy_sell_signals(profile)

        if signal == "buy" and usdt >= profile.MIN_TRADE_AMOUNT:
            qty = usdt / row["close"]
            usdt = 0
            asset = qty
            last_buy_price = row["close"]
            trades += 1
            print(f"🟢 BUY @ {row['close']:.4f}")
        elif signal == "sell" and asset > 0:
            usdt = asset * row["close"]
            pnl = ((row["close"] - last_buy_price) / last_buy_price) * 100
            print(f"🔴 SELL @ {row['close']:.4f} | PnL: {pnl:.2f}%")
            asset = 0

    final_balance = usdt if usdt > 0 else asset * df.iloc[-1]["close"]
    result = ((final_balance - 100) / 100) * 100
    print(f"\n📊 Итог: {final_balance:.2f} USDT ({result:.2f}%) за период")
    print(f"💼 Совершено сделок: {trades}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_name", nargs="?", default=None)
    parser.add_argument("--from-pkl", action="store_true")
    args = parser.parse_args()

    if args.from_pkl:
        with open("temp_profile.pkl", "rb") as f:
            profile = pickle.load(f)
    elif args.profile_name:
        profile_dict = get_profile_by_name(args.profile_name)
        profile = SimpleNamespace(**{k.upper(): v for k, v in profile_dict.items()})
    else:
        print("❌ Укажи имя профиля или --from-pkl")
        sys.exit(1)

    print(f"✅ Профиль: {profile.SYMBOL} | Таймфрейм: {profile.TIMEFRAME}")

    while True:
        try:
            start = input("📅 Введите дату начала (например: 1 Apr, 2025): ").strip()
            datetime.strptime(start, "%d %b, %Y")
            break
        except ValueError:
            print("❌ Формат неверный. Пример: 3 May, 2025")

    while True:
        try:
            end = input("📅 Введите дату окончания (например: 3 May, 2025): ").strip()
            datetime.strptime(end, "%d %b, %Y")
            break
        except ValueError:
            print("❌ Формат неверный. Пример: 3 May, 2025")

    df = fetch_klines(profile.SYMBOL, profile.TIMEFRAME, start, end)
    run_backtest(df, profile)