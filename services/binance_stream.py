import json
import threading
import asyncio
from websocket import create_connection

def _listen_thread(symbol: str, interval: str, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """
    Thread target: connect to Binance websocket and push closing prices into the asyncio.Queue.
    """
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
    ws = create_connection(url)
    
    try:
        while True:
            message = ws.recv()
            data = json.loads(message)
            k = data.get("k", {})
            if k.get("x"):  # candle is closed
                price = float(k["c"])
                # Schedule queue.put in the event loop thread-safe
                loop.call_soon_threadsafe(asyncio.create_task, queue.put(price))
    except Exception as e:
        # Здесь можно добавить логирование через utils.logger
        print(f"WebSocket thread error: {e}")
    finally:
        ws.close()

async def listen_klines(symbol: str, interval: str, queue: asyncio.Queue):
    """
    Start a background thread to listen to kline websocket and keep coroutine alive.
    """
    loop = asyncio.get_event_loop()
    thread = threading.Thread(
        target=_listen_thread,
        args=(symbol, interval, queue, loop),
        daemon=True
    )
    thread.start()
    # Keep coroutine alive indefinitely
    while True:
        await asyncio.sleep(3600)

