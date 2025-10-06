import os
import requests
from discord import SyncWebhook, Embed
from datetime import datetime, timedelta
import pytz
import time

# =============== CONFIGURATION ===============
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Make sure you added this in Render environment variables
TIMEZONE = pytz.timezone("Asia/Karachi")
SEND_HOUR = 8  # Send at 8 AM
# =============================================

def get_gold_price():
    """Fetch the latest gold price from a free public API."""
    try:
        url = "https://api.metals.live/v1/spot"
        response = requests.get(url, timeout=10)
        data = response.json()
        for item in data:
            if "gold" in item:
                return float(item["gold"])
        return None
    except Exception as e:
        print("Error fetching gold price:", e)
        return None

def get_sentiment():
    """Example placeholder sentiment logic."""
    try:
        # You can replace this with real sentiment data later
        return {
            "Overall Sentiment": "Bullish",
            "Market Confidence": "Strong",
            "Technical Bias": "Uptrend"
        }
    except Exception as e:
        print("Error fetching sentiment:", e)
        return None

def send_discord_update():
    """Send a nicely formatted message to the Discord webhook."""
    webhook = SyncWebhook.from_url(WEBHOOK_URL)
    embed = Embed(
        title="📈 Daily Gold Forecast Update",
        description=f"Here’s your morning update for gold price and market sentiment.",
        color=0xFFD700,
        timestamp=datetime.now(TIMEZONE)
    )

    gold_price = get_gold_price()
    sentiment_details = get_sentiment()

    if gold_price:
        embed.add_field(name="🏅 Gold Price (USD/oz)", value=f"${gold_price:,}", inline=False)
    else:
        embed.add_field(name="🏅 Gold Price (USD/oz)", value="⚠️ Could not fetch gold price", inline=False)

    if sentiment_details:
        sentiment_text = "\n".join([f"**{k}:** {v}" for k, v in sentiment_details.items()])
        embed.add_field(name="📊 Market Sentiment", value=sentiment_text, inline=False)
    else:
        embed.add_field(name="📊 Market Sentiment", value="⚠️ Could not fetch sentiment data", inline=False)

    embed.set_footer(text="Auto Gold Forecast Bot • Powered by Hasan Ali")
    webhook.send(embed=embed)
    print(f"✅ Update sent successfully at {datetime.now(TIMEZONE)}")

def run_scheduler():
    """Run loop to send the message at 8 AM daily."""
    print("🚀 Gold Forecast Bot is running...")
    while True:
        now = datetime.now(TIMEZONE)
        target_time = now.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)

        if now >= target_time and now < target_time + timedelta(minutes=1):
            send_discord_update()
            time.sleep(60)  # Wait a minute to prevent duplicate sends
        time.sleep(30)

if __name__ == "__main__":
    send_discord_update()  # Send immediately when starting (optional)
    run_scheduler()
