# 🤖 Binance Trading Bot

Python-based trading bot for automated cryptocurrency trading via Binance API.  
Supports RSI, MACD, EMA indicators and profile-based settings for different trading pairs.

---

## 🚀 Features

- Поддержка нескольких торговых профилей (XRP, BNB, DOGE и др.)
- Индикаторы: **RSI**, **MACD**, **EMA**
- Умное управление балансом: использует весь доступный USDT
- Гибкая логика сигналов (`buy` / `sell` / `hold`)
- Цветной лог в терминале и запись в файл
- Резервные расчёты индикаторов через `numpy`, если TA-Lib не установлен

---

## 🧱 Project Structure

```
Binance_trading_bot/
├── config/                # Settings and profiles
│   ├── settings.py
│   └── profiles/
│       ├── xrp.py
│       ├── bnb.py
│       └── doge.py
├── services/              # Basic logic
│   ├── binance_client.py
│   ├── technical_indicators.py
│   ├── trade_logic.py
│   └── order_execution.py
├── utils/                 # Auxiliary utilities
│   ├── quantity_utils.py
│   └── logger.py
├── tests/                 # Pytest tests
│   └── test_*.py
├── main.py                # Запуск бота
├── .env                   # API-ключи Binance
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## ⚙️ Installation

1. Clone the project:

```bash
git clone https://github.com/your-user/Binance_trading_bot.git
cd Binance_trading_bot
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file:

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
```

4. Run:

```bash
python main.py
```

---

## 📈 Trading Profiles

Trading settings are stored in `config/profiles/*.py`  
Example: `bnb.py`, `doge.py`, `xrp.py`  
Each profile can define:

- SYMBOL = 'BNBUSDT'
- Таймфрейм: '5m', '15m' и т.д.
- Используемые индикаторы: `USE_RSI`, `USE_MACD`, `USE_EMA`, и т.д.

---

## 🧪 Tests

Run all tests:

```bash
pytest
```

---

## 🐧 Installation TA-Lib на Linux

1. Install the C-library:

```bash
sudo apt install -y build-essential wget
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xvzf ta-lib-0.4.0-src.tar.gz
cd ta-lib
./configure --prefix=/usr
make
sudo make install
```

2. Install the Python wrapper:

```bash
export CFLAGS="-I/usr/include"
export LDFLAGS="-L/usr/lib"
pip install TA-Lib
```

If TA-Lib is not installed — the bot will use fallback functions based on `numpy`.

---

## 📄 License

MIT License
