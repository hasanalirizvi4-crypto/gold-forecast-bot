import sys
import types

# Patch for Python 3.13 where audioop is removed
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')


import os
import requests
from discord import SyncWebhook, Embed
from datetime import datetime, timedelta
import pytz
import time

# =============== CONFIGURATION ===============
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Add this in Render environment variables
TIMEZONE = pytz.timezone("Asia/Karachi")
SEND_HOUR = 8  # Send at 8 AM Pakistan time
# =============================================

# === GOLD PRICE FETCHER (Multiple Sources) ===
def get_gold_price():
    """Fetch the latest gold price from multiple sources for reliability."""
    try:
        # 🥇 Primary source: Metals.live (no API key)
        url1 = "https://api.metals.live/v1/spot"
        response1 = requests.get(url1, timeout=10)
        data1 = response1.json()
        for item in data1:
            if "gold" in item:
                return float(item["gold"])
    except Exception as e:
        print("Primary source failed:", e)

    try:
        # 🥈 Secondary source: GoldAPI.io
        headers = {"x-access-token": "goldapi-favtsmgcmdotp-io", "Content-Type": "application/json"}
        response2 = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        data2 = response2.json()
        if "price" in data2:
            return float(data2["price"])
    except Exception as e:
        print("Secondary source failed:", e)

    try:
        # 🥉 Backup source: Metals-API (unofficial)
        url3 = "https://metals-api.com/api/latest?base=USD&symbols=XAU"
        response3 = requests.get(url3, timeout=10)
        data3 = response3.json()
        if "rates" in data3 and "XAU" in data3["rates"]:
            return 1 / float(data3["rates"]["XAU"])
    except Exception as e:
        print("Backup source failed:", e)

    return None  # If all failed

# === SENTIMENT + BUY/SELL LEVELS ===
def get_sentiment():
    """Generate simulated sentiment data (can be upgraded with ForexFactory parsing)."""
    try:
        sentiment = {
            "Overall Sentiment": "Bullish",
            "Market Confidence": "Moderate",
            "ETF Flow": "Inflow",
            "USD Strength": "Weak",
        }
        return sentiment
    except Exception as e:
        print("Error fetching sentiment:", e)
        return None

def get_zones(price):
    """Derive buy/sell zones using technical confluence (daily range logic)."""
    if not price:
        return None, None

    # Simulate support/resistance zones using small percent offsets
    buy_zone_low = round(price * 0.995, 2)
    buy_zone_high = round(price * 0.997, 2)
    sell_zone_low = round(price * 1.003, 2)
    sell_zone_high = round(price * 1.005, 2)

    return (buy_zone_low, buy_zone_high), (sell_zone_low, sell_zone_high)

# === DISCORD MESSAGE SENDER ===
def send_discord_update():
    webhook = SyncWebhook.from_url(WEBHOOK_URL)
    embed = Embed(
        title="🏆 Daily Gold Forecast Update",
        description="Comprehensive gold forecast and trading zones for the day.",
        color=0xFFD700,
        timestamp=datetime.now(TIMEZONE)
    )

    gold_price = get_gold_price()
    sentiment_details = get_sentiment()

    # --- Price Section ---
    if gold_price:
        embed.add_field(name="🏅 Spot Gold Price (USD/oz)", value=f"${gold_price:,}", inline=False)
    else:
        embed.add_field(name="🏅 Spot Gold Price (USD/oz)", value="⚠️ Could not fetch gold price", inline=False)

    # --- Zones Section ---
    buy_zone, sell_zone = get_zones(gold_price)
    if buy_zone and sell_zone:
        embed.add_field(
            name="💰 Buy Zone",
            value=f"{buy_zone[0]} – {buy_zone[1]}",
            inline=True
        )
        embed.add_field(
            name="📈 Sell Zone",
            value=f"{sell_zone[0]} – {sell_zone[1]}",
            inline=True
        )
    else:
        embed.add_field(name="💰 Zones", value="Unavailable", inline=False)

    # --- Sentiment Section ---
    if sentiment_details:
        sentiment_text = "\n".join([f"**{k}:** {v}" for k, v in sentiment_details.items()])
        embed.add_field(name="🧠 Market Sentiment", value=sentiment_text, inline=False)
    else:
        embed.add_field(name="🧠 Market Sentiment", value="⚠️ Could not fetch sentiment data", inline=False)

    embed.set_footer(text="Auto Gold Forecast Bot • Powered by Hasan Ali")

    webhook.send(embed=embed)
    print(f"✅ Update sent successfully at {datetime.now(TIMEZONE)}")

# === SCHEDULER ===
def run_scheduler():
    print("🚀 Gold Forecast Bot is running and waiting for 8 AM Pakistan time...")
    while True:
        now = datetime.now(TIMEZONE)
        target_time = now.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)

        # If time is between 8:00 and 8:01 AM → send update
        if now >= target_time and now < target_time + timedelta(minutes=1):
            send_discord_update()
            time.sleep(60)  # Prevent duplicate sends
        time.sleep(30)

# === MAIN ===
if __name__ == "__main__":
    send_discord_update()  # Send immediately when started
    run_scheduler()
