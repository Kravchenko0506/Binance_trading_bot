import asyncio

CURRENT_STATE = {
    "running": False,
    "profile_name": None,
    "task": None
}

def get_status():
    return {
        "running": CURRENT_STATE["running"],
        "profile": CURRENT_STATE["profile_name"]
    }

async def start_trading(profile_name: str, runner_function):
    if CURRENT_STATE["running"]:
        return f"⚠️ Бот уже работает с профилем: {CURRENT_STATE['profile_name']}"

    CURRENT_STATE["profile_name"] = profile_name
    CURRENT_STATE["running"] = True

    # Запускаем торговлю как background-task
    CURRENT_STATE["task"] = asyncio.create_task(runner_function(profile_name))
    return f"🚀 Торговля запущена по профилю: {profile_name}"

async def stop_trading():
    if not CURRENT_STATE["running"]:
        return "⛔️ Бот уже остановлен."

    CURRENT_STATE["running"] = False
    CURRENT_STATE["profile_name"] = None

    task = CURRENT_STATE.get("task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    CURRENT_STATE["task"] = None
    return "🛑 Торговля остановлена."
