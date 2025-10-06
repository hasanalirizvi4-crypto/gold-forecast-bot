import sys, types

# 🩹 Patch for Python 3.13 (audioop issue fix)
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

import sys, types
import time
import requests
from datetime import datetime
import pytz
from discord import SyncWebhook, Embed

# ====== CONFIGURATION ======
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
TIMEZONE = pytz.timezone("Asia/Karachi")

# ====== FUNCTIONS ======

# --- Get Live Gold Price (via Yahoo Finance) ---
def get_gold_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        response = requests.get(url, timeout=10)
        data = response.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return float(price)
    except Exception as e:
        print(f"⚠️ Error fetching gold price: {e}")
        return None


# --- Sentiment Analysis (based on ForexFactory data) ---
def get_sentiment():
    try:
        news_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(news_url, timeout=10)
        events = response.json()

        gold_related = [e for e in events if "USD" in e.get("country", "") or "gold" in e.get("title", "").lower()]
        impact_summary = {"High": 0, "Medium": 0, "Low": 0}
        upcoming = []

        for event in gold_related:
            impact = event.get("impact", "Low")
            if impact in impact_summary:
                impact_summary[impact] += 1
            upcoming.append(event.get("title", "Unknown Event"))

        overall = "Neutral"
        if impact_summary["High"] >= 3:
            overall = "Volatile"
        elif impact_summary["Medium"] >= 2:
            overall = "Cautious Bullish"
        elif impact_summary["Low"] >= 3:
            overall = "Stable Bullish"

        return overall, impact_summary, upcoming[:5]

    except Exception as e:
        print(f"⚠️ Error fetching sentiment: {e}")
        return "Unknown", {}, []


# --- Define Support/Resistance Zones ---
def calculate_zones(price):
    support_zone = round(price - 10, 2)
    resistance_zone = round(price + 10, 2)
    buy_zone = f"{support_zone - 5} – {support_zone}"
    sell_zone = f"{resistance_zone} – {resistance_zone + 5}"
    return buy_zone, sell_zone


# --- Send Daily Update to Discord ---
def send_discord_update():
    price = get_gold_price()
    sentiment, sentiment_details, upcoming = get_sentiment()

    webhook = SyncWebhook.from_url(WEBHOOK_URL)

    if price:
        buy_zone, sell_zone = calculate_zones(price)

        embed = Embed(
            title="🏆 Daily Gold Forecast",
            description=f"**Live Gold Price:** ${price}\n\n**Sentiment:** {sentiment}",
            color=0xFFD700,
            timestamp=datetime.now(TIMEZONE)
        )
        embed.add_field(name="📈 Buy Zone", value=f"`{buy_zone}`", inline=True)
        embed.add_field(name="📉 Sell Zone", value=f"`{sell_zone}`", inline=True)
        embed.add_field(
            name="🧠 Sentiment Breakdown",
            value="\n".join([f"{k}: {v}" for k, v in sentiment_details.items()]) or "No data",
            inline=False
        )
        embed.add_field(
            name="📰 Upcoming USD/Gold Events",
            value="\n".join(upcoming) if upcoming else "No major events this week.",
            inline=False
        )
        embed.set_footer(text="Automated Gold Market Update | Source: Yahoo Finance + ForexFactory")

    else:
        embed = Embed(
            title="⚠️ Could Not Fetch Gold Price",
            description="The bot couldn’t retrieve the current gold rate. It will retry in the next cycle.",
            color=0xFF0000,
            timestamp=datetime.now(TIMEZONE)
        )

    webhook.send(embed=embed)


# ====== SCHEDULER ======
def run_bot():
    print("✅ Gold Forecast Bot Running 24/7...")
    while True:
        now = datetime.now(TIMEZONE)
        # Daily forecast at 7 AM Pakistan time
        if now.hour == 7 and now.minute == 0:
            send_discord_update()
            time.sleep(60)  # Wait 1 minute to prevent duplicates
        else:
            time.sleep(30)


# ====== MAIN EXECUTION ======
if __name__ == "__main__":
    send_discord_update()  # Optional: send one immediately
    run_bot()
