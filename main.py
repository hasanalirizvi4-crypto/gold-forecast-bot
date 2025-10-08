import requests
import time
import datetime
import schedule
from collections import deque

# === CONFIG ===
DISCORD_WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL"  # 🔹 Replace with your webhook
METALS_API_KEY = "a255414b6c7af4586f3b4696bd444950"
ALL_TIME_HIGH = 2430.50
PRICE_CHANGE_THRESHOLD_PCT = 1.0
HISTORY_LIMIT = 120
FAST_SMA_WINDOW = 5
SLOW_SMA_WINDOW = 20
FETCH_INTERVAL_SECONDS = 60
# ==============

price_history = deque(maxlen=HISTORY_LIMIT)
last_alert_price = None
last_fast_sma = None
last_slow_sma = None


def send_alert(title, message, color=0xFFD700):
    data = {
        "username": "GoldBot Lite 🦅",
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "footer": {"text": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}
        }]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        if r.status_code not in (200, 204):
            print("Webhook error:", r.status_code, r.text)
    except Exception as e:
        print("Failed to send alert:", e)


def fetch_spot_gold():
    """Fetch spot gold price (USD per XAU) from Metals API and fallback sources."""
    # 1️⃣ Metals API
    try:
        url = f"https://metals-api.com/api/latest?access_key={METALS_API_KEY}&base=USD&symbols=XAU"
        resp = requests.get(url, timeout=8).json()
        rate = resp.get("rates", {}).get("XAU")
        if rate:
            price = 1 / rate if rate < 1 else rate
            if price > 10:
                return round(price, 2)
    except Exception as e:
        print("Metals API error:", e)

    # 2️⃣ Fallback public source
    try:
        res = requests.get("https://api.exchangerate.host/convert?from=XAU&to=USD", timeout=8).json()
        if res.get("result") and res["result"] > 10:
            return round(float(res["result"]), 2)
    except Exception as e:
        print("Fallback API error:", e)

    return None


def sma(prices, window):
    return sum(prices[-window:]) / window if len(prices) >= window else None


def analyze():
    global last_alert_price, last_fast_sma, last_slow_sma

    price = fetch_spot_gold()
    if not price:
        print(f"[{datetime.datetime.utcnow()}] ⚠️ Could not fetch spot gold price.")
        return

    now = datetime.datetime.utcnow()
    price_history.append(price)
    print(f"[{now}] Spot Gold: ${price:.2f}")

    # === Price move alert ===
    if last_alert_price:
        pct = ((price - last_alert_price) / last_alert_price) * 100
        if abs(pct) >= PRICE_CHANGE_THRESHOLD_PCT:
            direction = "UP" if pct > 0 else "DOWN"
            send_alert(
                f"💰 Gold Price {direction} {pct:.2f}%",
                f"Current: **${price:.2f}** | Previous: ${last_alert_price:.2f}",
                0x00FF00 if pct > 0 else 0xFF0000
            )
            last_alert_price = price
    else:
        last_alert_price = price

    # === ATH alert ===
    if price >= ALL_TIME_HIGH:
        send_alert("🚀 Gold Breaks All-Time High!", f"Current price: **${price:.2f}**", 0xFFD700)

    # === SMA trend detection ===
    fast_sma = sma(list(price_history), FAST_SMA_WINDOW)
    slow_sma = sma(list(price_history), SLOW_SMA_WINDOW)

    if fast_sma and slow_sma and last_fast_sma and last_slow_sma:
        prev_diff = last_fast_sma - last_slow_sma
        now_diff = fast_sma - slow_sma
        if prev_diff <= 0 < now_diff:
            send_alert("📈 Bullish SMA Crossover",
                       f"Fast SMA ({FAST_SMA_WINDOW}) crossed above Slow SMA ({SLOW_SMA_WINDOW})\n"
                       f"Price: ${price:.2f}", 0x00FF00)
        elif prev_diff >= 0 > now_diff:
            send_alert("📉 Bearish SMA Crossover",
                       f"Fast SMA ({FAST_SMA_WINDOW}) crossed below Slow SMA ({SLOW_SMA_WINDOW})\n"
                       f"Price: ${price:.2f}", 0xFF0000)

    last_fast_sma, last_slow_sma = fast_sma, slow_sma


def run():
    send_alert("🤖 GoldBot Online", "Bot is now monitoring spot gold prices 24/7 🌍", 0x00FFFF)
    analyze()
    schedule.every(FETCH_INTERVAL_SECONDS).seconds.do(analyze)

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run()
