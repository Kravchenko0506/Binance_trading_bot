import json
import os
import subprocess
from config.settings import (
    COMMISSION_RATE, MIN_PROFIT_RATIO, STOP_LOSS_RATIO,
    TAKE_PROFIT_RATIO, PRICE_PRECISION, MIN_ORDER_QUANTITY, MIN_TRADE_AMOUNT
)

PROFILE_FILE = os.path.join("config", "profiles.json")

# === Работа с файлами ===

def load_profiles():
    if not os.path.exists(PROFILE_FILE):
        return {}
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_profiles(profiles):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


# === Утилиты ===

def list_profiles(profiles):
    if not profiles:
        print("📭 Профили не найдены.")
        return
    print("\n📁 Доступные профили:")
    for name in profiles:
        print(f" - {name}")

def remove_profile(profiles):
    if not profiles:
        print("📭 Нет доступных профилей для удаления.")
        return

    print("\n📁 Доступные профили:")
    for name in profiles:
        print(f" - {name}")

    name = input("\nВведите имя профиля для удаления: ").strip().lower()
    if name not in profiles:
        print(f"❌ Профиль '{name}' не найден.")
        return

    confirm = input(f"⚠️ Удалить профиль '{name}'? (y/n): ").strip().lower()
    if confirm == 'y':
        del profiles[name]
        save_profiles(profiles)
        print(f"🗑️ Профиль '{name}' удалён.")
    else:
        print("↩️ Отмена удаления.")



# === Добавление профиля ===

def add_profile(profiles):
    print("\n🆕 Добавление нового профиля")
    print("🔹 Нажмите Enter, чтобы оставить значение по умолчанию\n")

    name = input("📝 Имя профиля (например: xrp): ").strip().lower()
    if name in profiles:
        overwrite = input(f"⚠️ Профиль '{name}' уже существует. Перезаписать? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("↩️ Отмена создания.")
            return

    def ask_param(key, default, comment=None):
        prompt = f"• {key} [{default}]"
        if comment:
            prompt += f" – {comment}"
        prompt += ": "
        val = input(prompt).strip()
        return cast(val, default)

    def cast(val, base):
        if val == '':
            return base
        if isinstance(base, bool):
            return val.lower() in ['true', '1', 'y']
        if isinstance(base, int):
            return int(val)
        if isinstance(base, float):
            return float(val)
        return val

    profile = {}
    profile["symbol"] = input("🔸 Торговая пара (например: XRPUSDT): ").strip().upper()
    valid_timeframes = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h", "1d"
]

    while True:
        tf = input(f"🔸 Таймфрейм ({'/'.join(valid_timeframes)}): ").strip()
        if tf in valid_timeframes:
            profile["timeframe"] = tf
            break
        else:
            print("❌ Неверный таймфрейм. Попробуй снова.")


    print("\n📊 Индикаторы:")

    profile["use_rsi"] = ask_param("use_rsi", True, "использовать RSI?")
    if profile["use_rsi"]:
        profile["rsi_period"] = ask_param("rsi_period", 14)
        profile["rsi_overbought"] = ask_param("rsi_overbought", 70)
        profile["rsi_oversold"] = ask_param("rsi_oversold", 35)

    profile["use_macd"] = ask_param("use_macd", True, "использовать MACD?")
    if profile["use_macd"]:
        profile["macd_fast_period"] = ask_param("macd_fast_period", 8)
        profile["macd_slow_period"] = ask_param("macd_slow_period", 21)
        profile["macd_signal_period"] = ask_param("macd_signal_period", 9)

    profile["use_macd_for_buy"] = ask_param("use_macd_for_buy", True)
    profile["use_macd_for_sell"] = ask_param("use_macd_for_sell", True)

    profile["use_ema"] = ask_param("use_ema", False, "использовать EMA-фильтр?")
    if profile["use_ema"]:
        profile["ema_period"] = ask_param("ema_period", 50)

    print("\n⚙️ Торговые параметры:")

    default_extra = {
        "commission_rate": COMMISSION_RATE,
        "min_profit_ratio": MIN_PROFIT_RATIO,
        "stop_loss_ratio": STOP_LOSS_RATIO,
        "take_profit_ratio": TAKE_PROFIT_RATIO,
        "price_precision": PRICE_PRECISION,
        "min_order_quantity": MIN_ORDER_QUANTITY,
        "min_trade_amount": MIN_TRADE_AMOUNT,
    }

    for key, default in default_extra.items():
        profile[key] = ask_param(key, default)

    profiles[name] = profile
    save_profiles(profiles)
    print(f"\n✅ Профиль '{name}' успешно создан и сохранён.")


# === Редактирование ===

def edit_profile(profiles):
    print("\n✏️ Редактирование существующего профиля")
    name = input("🔸 Введите имя профиля для редактирования: ").strip().lower()

    if name not in profiles:
        print(f"❌ Профиль '{name}' не найден.")
        return

    profile = profiles[name]

    def ask_param(key, current, comment=None):
        prompt = f"• {key} ({current})"
        if comment:
            prompt += f" – {comment}"
        prompt += ": "
        val = input(prompt).strip()
        return cast(val, current)

    def cast(val, base):
        if val == '':
            return base
        if isinstance(base, bool):
            return val.lower() in ['true', '1', 'y']
        if isinstance(base, int):
            return int(val)
        if isinstance(base, float):
            return float(val)
        return val

    print("\n🔧 Основные параметры:")
    profile["symbol"] = ask_param("symbol", profile.get("symbol", "")).upper()
    valid_timeframes = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h", "1d"
]

    while True:
        current = profile.get("timeframe", "")
        tf = input(f"🔸 Таймфрейм ({current}) [{'/'.join(valid_timeframes)}]: ").strip()
        if tf == '':
            profile["timeframe"] = current
            break
        elif tf in valid_timeframes:
            profile["timeframe"] = tf
            break
        else:
            print("❌ Неверный таймфрейм. Попробуй снова.")


    print("\n📊 Индикаторы:")
    profile["use_rsi"] = ask_param("use_rsi", profile.get("use_rsi", True))
    if profile["use_rsi"]:
        profile["rsi_period"] = ask_param("rsi_period", profile.get("rsi_period", 14))
        profile["rsi_overbought"] = ask_param("rsi_overbought", profile.get("rsi_overbought", 70))
        profile["rsi_oversold"] = ask_param("rsi_oversold", profile.get("rsi_oversold", 35))

    profile["use_macd"] = ask_param("use_macd", profile.get("use_macd", True))
    if profile["use_macd"]:
        profile["macd_fast_period"] = ask_param("macd_fast_period", profile.get("macd_fast_period", 8))
        profile["macd_slow_period"] = ask_param("macd_slow_period", profile.get("macd_slow_period", 21))
        profile["macd_signal_period"] = ask_param("macd_signal_period", profile.get("macd_signal_period", 9))

    profile["use_macd_for_buy"] = ask_param("use_macd_for_buy", profile.get("use_macd_for_buy", True))
    profile["use_macd_for_sell"] = ask_param("use_macd_for_sell", profile.get("use_macd_for_sell", True))

    profile["use_ema"] = ask_param("use_ema", profile.get("use_ema", False))
    if profile["use_ema"]:
        profile["ema_period"] = ask_param("ema_period", profile.get("ema_period", 50))

    print("\n⚙️ Торговые параметры:")
    trade_fields = [
        "commission_rate", "min_profit_ratio", "stop_loss_ratio",
        "take_profit_ratio", "price_precision", "min_order_quantity", "min_trade_amount"
    ]
    for key in trade_fields:
        profile[key] = ask_param(key, profile.get(key))

    profiles[name] = profile
    save_profiles(profiles)
    print(f"\n✅ Профиль '{name}' успешно обновлён.")


# === Меню ===

if __name__ == "__main__":
    while True:
        print("\n🧠 Меню управления профилями")
        print("1. Показать профили")
        print("2. Добавить профиль")
        print("3. Удалить профиль")
        print("4. Редактировать профиль")
        print("5. Запустить по профилю (торговля или тест)")
        print("6. Выход")
        choice = input("\nВыбери действие (1-6): ").strip()

        if choice == '1':
            profiles = load_profiles()
            list_profiles(profiles)

        elif choice == '2':
            profiles = load_profiles()
            add_profile(profiles)

        elif choice == '3':
            profiles = load_profiles()
            remove_profile(profiles)

        elif choice == '4':
            profiles = load_profiles()
            edit_profile(profiles)

        elif choice == '5':
            profiles = load_profiles()
            if not profiles:
                print("📭 Нет доступных профилей. Сначала создай хотя бы один.")
                continue

            print("\n📁 Доступные профили:")
            for name in profiles:
                print(f" - {name}")

            profile_name = input("\nВведите имя профиля для запуска: ").strip().lower()
            if not profile_name:
                print("❌ Имя профиля не может быть пустым.")
                continue
            if profile_name not in profiles:
                print(f"❌ Профиль '{profile_name}' не найден.")
                continue

            print(f"\n🧩 Выбран профиль: {profile_name}")
            print("Что сделать с этим профилем?")
            print("1. 🚀 Запустить торговлю")
            print("2. 🧪 Запустить бэктест")
            print("3. ↩️ Назад")
            action = input("Выбор (1/2/3): ").strip()

            if action == '1':
                subprocess.run(["python", "run_trading_stream.py", profile_name])
            elif action == '2':
                subprocess.run(["python", "backtest.py", profile_name])
            else:
                print("↩️ Назад в меню")


        elif choice == '6':
            print("👋 Выход из менеджера профилей.")
            break
        else:
            print("❌ Неверный выбор")




