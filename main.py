import requests
import datetime
import pytz
import time
import traceback
from discord import SyncWebhook, Embed

# === Discord Webhook ===
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
webhook = SyncWebhook.from_url(WEBHOOK_URL)

# === Helper to send embedded messages ===
def send_embed(title, description, color=0xFFD700, fields=None):
    embed = Embed(title=title, description=description, color=color, timestamp=datetime.datetime.utcnow())
    if fields:
        for field in fields:
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
    embed.set_footer(text="Gold Forecast Bot • Auto Analysis")
    webhook.send(embed=embed)

# === Get real-time gold price (XAU/USD) ===
def get_gold_price():
    try:
        url = "https://api.metals.live/v1/spot/gold"
        r = requests.get(url, timeout=10)
        data = r.json()
        if isinstance(data, list) and len(data) > 0 and "price" in data[-1]:
            return float(data[-1]["price"])
    except Exception:
        return None
    return None

# === Generate main daily forecast ===
def generate_daily_report():
    try:
        price = get_gold_price()
        if not price:
            send_embed("⚠️ Gold Report Error", "Could not fetch gold price.")
            return

        # --- Basic calculated levels (adjust logic later) ---
        buy_zone_low = price - 8
        buy_zone_high = price - 4
        sell_zone_low = price + 4
        sell_zone_high = price + 8

        buy_zone = f"{buy_zone_low:.2f} – {buy_zone_high:.2f}"
        sell_zone = f"{sell_zone_low:.2f} – {sell_zone_high:.2f}"

        sentiment = "Bullish" if price % 2 == 0 else "Bearish"

        fields = [
            {"name": "Current Price", "value": f"${price}", "inline": True},
            {"name": "Buy Zone", "value": buy_zone, "inline": True},
            {"name": "Sell Zone", "value": sell_zone, "inline": True},
            {"name": "Market Sentiment", "value": sentiment, "inline": False},
            {"name": "Comment", "value": f"Gold appears {sentiment.lower()} — consider trades near respective zones."}
        ]
        send_embed("📊 Daily Gold Report", "Automated forecast for XAU/USD.", fields=fields)
        return (buy_zone_low, buy_zone_high, sell_zone_low, sell_zone_high)

    except Exception as e:
        send_embed("⚠️ Error in Daily Report", f"```\n{traceback.format_exc()}\n```", color=0xFF0000)
        return None

# === Check live price every minute ===
def monitor_price(zones):
    buy_low, buy_high, sell_low, sell_high = zones
    while True:
        try:
            price = get_gold_price()
            if not price:
                time.sleep(60)
                continue

            # Check for buy zone re-entry
            if buy_low <= price <= buy_high:
                send_embed(
                    "💰 Gold Buy Zone Alert",
                    f"Price re-entered buy zone at **${price:.2f}**.\nConsider long entries.",
                    color=0x32CD32
                )

            # Check for sell zone re-entry
            elif sell_low <= price <= sell_high:
                send_embed(
                    "📉 Gold Sell Zone Alert",
                    f"Price re-entered sell zone at **${price:.2f}**.\nConsider short entries.",
                    color=0xFF6347
                )

            time.sleep(60)  # check every 1 min
        except Exception:
            time.sleep(60)

# === Daily scheduling ===
def schedule_daily_task():
    pk_tz = pytz.timezone("Asia/Karachi")
    while True:
        now = datetime.datetime.now(pk_tz)
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now > target:
            target += datetime.timedelta(days=1)
        sleep_time = (target - now).total_seconds()
        time.sleep(sleep_time)

        zones = generate_daily_report()
        if zones:
            monitor_price(zones)

# === On startup ===
def startup_message():
    send_embed(
        "✅ Gold Forecast Bot Active",
        "Bot successfully deployed on Render.\n\nDaily report scheduled for **8 AM Pakistan Time**.\nIt will also alert whenever gold re-enters key buy/sell zones.",
        color=0x1E90FF
    )

# === Main ===
if __name__ == "__main__":
    startup_message()
    generate_daily_report()  # optional immediate report on start
    schedule_daily_task()
