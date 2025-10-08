import requests
import time
import datetime
import schedule
from collections import deque

# === CONFIG ===
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"  # 🔹 Replace with your actual Discord webhook
GOLD_API_KEY = "goldapi-favtsmgcmdotp-io"          # 🔹 Your GoldAPI.io key
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
    """Send formatted alert message to Discord."""
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
    """Fetch real-time spot gold (XAU/USD) using GoldAPI.io."""
    url = "https://www.goldapi.io/api/XAU/USD"
    headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}

    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()

        if res.status_code == 200 and "price" in data:
            return round(float(data["price"]), 2)
        else:
            print("GoldAPI error:", res.status_code, data)
            return None
    except Exception as e:
        print("Fetch error:", e)
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
    send_alert("🤖 GoldBot Online", "Bot is now monitoring live gold prices (via GoldAPI.io) 🌍", 0x00FFFF)
    analyze()
    schedule.every(FETCH_INTERVAL_SECONDS).seconds.do(analyze)

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run()
