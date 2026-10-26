"""Tools the agent can call. Gemini reads each function's docstring and type hints
to decide when and how to call it, so keep them clear.

To add a new tool: write a function here and add it to TOOLS at the bottom.
"""
import ast
import ctypes
import operator
import os
import threading
import time
from datetime import datetime, timedelta

import psutil
import requests

HEADERS = {"User-Agent": "JarvisVoiceAgent/1.0 (personal demo)"}  # Wikipedia requires one

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "rain showers", 81: "heavy rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


# ---------- Weather ----------
def _find_city(city: str) -> dict | None:
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": city, "count": 1}, timeout=10).json()
    return geo["results"][0] if geo.get("results") else None


def get_weather(city: str) -> dict:
    """Get today's weather for a city: current temperature, conditions, humidity,
    wind, today's min/max temperature and chance of rain.

    Args:
        city: Name of the city, for example "Mumbai" or "Lucknow" or "London".
    """
    place = _find_city(city)
    if not place:
        return {"error": f"Could not find a city named '{city}'."}
    data = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 1,
        },
        timeout=10,
    ).json()
    cur, day = data["current"], data["daily"]
    return {
        "location": f"{place['name']}, {place.get('country', '')}",
        "condition": WEATHER_CODES.get(cur["weather_code"], "unknown"),
        "temperature_c": cur["temperature_2m"],
        "humidity_percent": cur["relative_humidity_2m"],
        "wind_kmh": cur["wind_speed_10m"],
        "today_max_c": day["temperature_2m_max"][0],
        "today_min_c": day["temperature_2m_min"][0],
        "rain_chance_percent": day["precipitation_probability_max"][0],
    }


def get_weather_forecast(city: str, days: int = 7) -> dict:
    """Get the daily weather forecast for the coming days (tomorrow, this week, the weekend).
    Use this for questions like "will it rain tomorrow?" or "weather this week".

    Args:
        city: Name of the city.
        days: How many days to forecast, starting today (1-7).
    """
    place = _find_city(city)
    if not place:
        return {"error": f"Could not find a city named '{city}'."}
    d = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": max(1, min(int(days), 7)),
        },
        timeout=10,
    ).json()["daily"]
    return {
        "location": f"{place['name']}, {place.get('country', '')}",
        "days": [
            {
                "date": datetime.fromisoformat(date).strftime("%A %d %B"),
                "condition": WEATHER_CODES.get(code, "unknown"),
                "max_c": hi, "min_c": lo, "rain_chance_percent": rain,
            }
            for date, code, hi, lo, rain in zip(d["time"], d["weather_code"], d["temperature_2m_max"],
                                                d["temperature_2m_min"], d["precipitation_probability_max"])
        ],
    }


# ---------- Time ----------
def get_current_time() -> dict:
    """Get the current local date and time."""
    now = datetime.now()
    return {"date": now.strftime("%A, %d %B %Y"), "time": now.strftime("%I:%M %p")}


# ---------- Calculator ----------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** ( ) are allowed")


def calculate(expression: str) -> dict:
    """Calculate a maths expression exactly. Always use this for arithmetic instead of guessing.

    Args:
        expression: A maths expression using numbers and + - * / // % ** and brackets,
            for example "245 * 18" or "(1200 * 18) / 100" for 18% of 1200.
    """
    try:
        result = _eval(ast.parse(expression.replace("^", "**").replace("x", "*"), mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return {"error": f"Could not calculate '{expression}': {e}"}
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": round(result, 6) if isinstance(result, float) else result}


# ---------- Open websites and apps ----------
WEBSITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "wikipedia": "https://www.wikipedia.org", "linkedin": "https://www.linkedin.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "twitter": "https://x.com", "x": "https://x.com", "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com", "netflix": "https://www.netflix.com",
    "whatsapp": "https://web.whatsapp.com", "chatgpt": "https://chatgpt.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
}


def open_website(site: str) -> dict:
    """Open a website in the web browser.

    Args:
        site: A website name like "YouTube", "Gmail" or "GitHub", or an address like "example.com".
    """
    name = site.lower().strip()
    if name in WEBSITES:
        url = WEBSITES[name]
    elif "." in name:
        url = name if name.startswith("http") else f"https://{name}"
    else:
        url = f"https://www.{name.replace(' ', '')}.com"
    os.startfile(url)
    return {"opened": url}


# Only apps in this list can be opened. Add more as "spoken name": "program or URI".
APPS = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "command prompt": "cmd.exe", "cmd": "cmd.exe", "powershell": "powershell.exe",
    "task manager": "taskmgr.exe", "settings": "ms-settings:", "camera": "microsoft.windows.camera:",
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "spotify": "spotify:", "whatsapp": "whatsapp:",
}


def open_app(app_name: str) -> dict:
    """Open an application on this Windows computer, like Notepad, Calculator, Paint,
    File Explorer, Settings, Chrome, Word, Excel or VS Code.

    Args:
        app_name: Name of the app, for example "notepad" or "calculator".
    """
    name = app_name.lower().strip().removesuffix(" app")
    if name not in APPS:
        return {"error": f"I don't know how to open '{app_name}'.", "apps_i_can_open": sorted(APPS)}
    try:
        os.startfile(APPS[name])
    except OSError:
        return {"error": f"'{app_name}' does not seem to be installed on this computer."}
    return {"opened": app_name}


# ---------- Close apps and website tabs ----------
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
# spoken name: (process names, exact window title for Microsoft Store apps)
CLOSABLE_APPS = {
    "notepad": ({"notepad.exe"}, None),
    "calculator": ({"calculatorapp.exe", "calculator.exe"}, "Calculator"),
    "paint": ({"mspaint.exe"}, None),
    "settings": ({"systemsettings.exe"}, "Settings"),
    "camera": ({"windowscamera.exe"}, "Camera"),
    "task manager": ({"taskmgr.exe"}, "Task Manager"),
    "chrome": ({"chrome.exe"}, None), "google chrome": ({"chrome.exe"}, None),
    "edge": ({"msedge.exe"}, None), "microsoft edge": ({"msedge.exe"}, None),
    "word": ({"winword.exe"}, None), "excel": ({"excel.exe"}, None),
    "powerpoint": ({"powerpnt.exe"}, None),
    "vs code": ({"code.exe"}, None), "vscode": ({"code.exe"}, None),
    "visual studio code": ({"code.exe"}, None),
    "spotify": ({"spotify.exe"}, None),
    "whatsapp": ({"whatsapp.exe", "whatsapp.root.exe"}, "WhatsApp"),
}
NEVER_CLOSE = {"cmd", "command prompt", "powershell", "terminal", "windows terminal"}  # Jarvis runs in one


def _open_windows() -> list[tuple[int, str, str]]:
    """All visible top-level windows as (handle, process name, title)."""
    import win32gui
    import win32process

    found = []

    def visit(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if win32gui.IsWindowVisible(hwnd) and title:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name().lower()
            except psutil.Error:
                name = ""
            if pid != os.getpid():  # never touch Jarvis's own window
                found.append((hwnd, name, title))

    win32gui.EnumWindows(visit, None)
    return found


def _close_window(hwnd: int) -> None:
    import win32con
    import win32gui

    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)  # same as clicking the window's X


def _close_browser_tab(hwnd: int) -> bool:
    """Bring a browser window to the front and press Ctrl+W to close its current tab."""
    import win32api
    import win32con
    import win32gui

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    # Windows only lets a background program switch windows right after a key press.
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    finally:
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.3)
    if win32gui.GetForegroundWindow() != hwnd:
        return False  # safety: never send Ctrl+W to some other window
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("W"), 0, 0, 0)
    win32api.keybd_event(ord("W"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    return True


def close_app(name: str) -> dict:
    """Close an app or a website that is open, like Notepad, Calculator, Paint, WhatsApp,
    Word, Chrome, or a website tab such as YouTube or Gmail. For a website only that
    tab is closed, not the whole browser. Call once per thing to close.

    Args:
        name: What to close, for example "notepad", "youtube" or "whatsapp".
    """
    key = name.lower().strip().removesuffix(" app").removesuffix(" tab").removesuffix(" website")
    if key in NEVER_CLOSE:
        return {"error": f"I won't close {name}, because I might be running inside it."}
    windows = _open_windows()
    closed = []

    if key in ("file explorer", "explorer", "files"):
        import win32gui
        for hwnd, _, title in windows:
            if win32gui.GetClassName(hwnd) == "CabinetWClass":  # folder windows, not the taskbar
                _close_window(hwnd)
                closed.append(title)
    elif key in CLOSABLE_APPS:
        processes, store_title = CLOSABLE_APPS[key]
        for hwnd, proc, title in windows:
            if proc in processes or (store_title and title == store_title):
                _close_window(hwnd)
                closed.append(title)

    if not closed and len(key) >= 3:  # maybe it's a website open in a browser tab
        for hwnd, proc, title in windows:
            if proc in BROWSERS and key in title.lower() and _close_browser_tab(hwnd):
                closed.append(title)

    if not closed:
        return {"error": f"I couldn't find '{name}' open. A website tab can only be closed "
                         "if it's the tab currently showing in its browser window."}
    return {"closed": closed}


# ---------- Wikipedia ----------
def wikipedia_summary(topic: str) -> dict:
    """Look up a person, place or thing on Wikipedia and get a short summary.
    Use this for "who is ...", "what is ...", "tell me about ..." questions.

    Args:
        topic: What to look up, for example "APJ Abdul Kalam" or "Taj Mahal".
    """
    found = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": topic, "srlimit": 1, "format": "json"},
        headers=HEADERS, timeout=10,
    ).json()["query"]["search"]
    if not found:
        return {"error": f"Nothing found on Wikipedia for '{topic}'."}
    title = found[0]["title"]
    page = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
                        headers=HEADERS, timeout=10).json()
    return {"title": page.get("title", title), "summary": page.get("extract", "")}


# ---------- Currency ----------
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money from one currency to another using today's exchange rate.

    Args:
        amount: How much money, for example 100.
        from_currency: 3-letter currency code to convert from, for example "USD" for dollars.
        to_currency: 3-letter currency code to convert to, for example "INR" for rupees.
    """
    src, dst = from_currency.upper().strip(), to_currency.upper().strip()
    data = requests.get(f"https://open.er-api.com/v6/latest/{src}", timeout=10).json()
    if data.get("result") != "success" or dst not in data.get("rates", {}):
        return {"error": f"Could not convert {src} to {dst}. Use 3-letter codes like USD, INR, EUR."}
    rate = data["rates"][dst]
    return {"amount": amount, "from": src, "to": dst, "rate": rate, "result": round(amount * rate, 2)}


# ---------- Reminders ----------
def _default_reminder(message: str):
    from voice import speak  # imported here so tools.py works without a microphone
    speak(f"Reminder: {message}")


# The desktop app replaces this so reminders also show up in its chat.
on_reminder = _default_reminder


def _fire_reminder(message: str):
    threading.Thread(  # pop-up window that stays on top of everything
        target=ctypes.windll.user32.MessageBoxW, args=(0, message, "Jarvis reminder", 0x40000 | 0x1000),
        daemon=True,
    ).start()
    on_reminder(message)


def set_reminder(minutes: float, message: str) -> dict:
    """Set a reminder or timer. After the given time, Jarvis says the message out loud
    and shows a pop-up. Reminders are lost if Jarvis is closed.

    Args:
        minutes: How many minutes from now, for example 5. Use 0.5 for 30 seconds, 60 for an hour.
        message: What to remind about, for example "drink water" or "timer finished".
    """
    timer = threading.Timer(minutes * 60, _fire_reminder, args=(message,))
    timer.daemon = True
    timer.start()
    at = datetime.now() + timedelta(minutes=minutes)
    return {"reminder_set_for": at.strftime("%I:%M:%S %p"), "message": message}


# ---------- System info ----------
def get_system_info() -> dict:
    """Get this computer's battery percentage, whether it is charging, and CPU and memory usage."""
    info = {
        "cpu_usage_percent": psutil.cpu_percent(interval=0.5),
        "memory_usage_percent": psutil.virtual_memory().percent,
    }
    battery = psutil.sensors_battery()
    if battery:
        info["battery_percent"] = round(battery.percent)
        info["charging"] = battery.power_plugged
    else:
        info["battery"] = "no battery found (desktop PC)"
    return info


from rag import list_documents, search_documents  # noqa: E402  (RAG tools live in rag.py)

TOOLS = [
    get_weather, get_weather_forecast, get_current_time, calculate, open_website, open_app,
    wikipedia_summary, convert_currency, set_reminder, get_system_info, close_app,
    search_documents, list_documents,
]
