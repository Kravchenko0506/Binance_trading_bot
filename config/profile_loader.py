import json
import os
import sys
from config.settings import COMMISSION_RATE, MIN_PROFIT_RATIO, STOP_LOSS_RATIO, TAKE_PROFIT_RATIO, PRICE_PRECISION, MIN_ORDER_QUANTITY, MIN_TRADE_AMOUNT

PROFILE_FILE = os.path.join("config", "profiles.json")

DEFAULT_PARAMS = {
    "commission_rate": COMMISSION_RATE,
    "min_profit_ratio": MIN_PROFIT_RATIO,
    "stop_loss_ratio": STOP_LOSS_RATIO,
    "take_profit_ratio": TAKE_PROFIT_RATIO,
    "price_precision": PRICE_PRECISION,
    "min_order_quantity": MIN_ORDER_QUANTITY,
    "min_trade_amount": MIN_TRADE_AMOUNT
}

def get_profile_by_name(name):
    if not os.path.exists(PROFILE_FILE):
        raise FileNotFoundError("profiles.json не найден")

    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    if name not in profiles:
        print(f"❌ Профиль '{name}' не найден.")
        sys.exit(1)

    profile = DEFAULT_PARAMS.copy()
    profile.update(profiles[name])
    return profile

def load_profiles():
    if not os.path.exists(PROFILE_FILE):
        return {}
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
