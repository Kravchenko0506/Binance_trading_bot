import json
import threading
import asyncio
from websocket import create_connection
from utils.logger import system_logger

# Глобальный флаг остановки
stop_event = threading.Event()


def _listen_thread(symbol: str, interval: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
    try:
        ws = create_connection(url)
        system_logger.info(f"🌐 Подключен к WebSocket {symbol} [{interval}]")
        while not stop_event.is_set():
            message = ws.recv()
            data = json.loads(message)
            k = data.get("k", {})
            if k.get("x"):  # если свеча закрыта
                price = float(k["c"])
                loop.call_soon_threadsafe(asyncio.create_task, queue.put(price))
    except Exception as e:
       system_logger.exception(f"❌ Ошибка в WebSocket потоке: {e}")
    finally:
        ws.close()
        system_logger.info("🔌 WebSocket соединение закрыто")


async def listen_klines(symbol: str, interval: str, queue: asyncio.Queue):
    loop = asyncio.get_event_loop()
    thread = threading.Thread(
        target=_listen_thread,
        args=(symbol, interval, queue, loop),
        daemon=True
    )
    thread.start()
    try:
        while not stop_event.is_set():
            await asyncio.sleep(3600)  # поддержка живого цикла
    except asyncio.CancelledError:
        system_logger.info("🟡 WebSocket задача отменена (listen_klines)")


def stop_websocket():
    system_logger.info("🛑 Вызван stop_websocket() — завершение WebSocket потока")
    stop_event.set()
