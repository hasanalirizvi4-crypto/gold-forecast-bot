import sys
import types
import os
import time
import pytz
import requests
from datetime import datetime, timedelta
from discord import SyncWebhook, Embed

# === PATCH for Python 3.13 missing audioop ===
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

# =============== CONFIGURATION ===============
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
HF_TOKEN = os.getenv("HF_TOKEN")
TIMEZONE = pytz.timezone("Asia/Karachi")
SEND_HOUR = 8  # Daily forecast time (8 AM Pakistan)
# =============================================

# === 1. FETCH GOLD PRICE (Yahoo Finance) ===
def get_gold_price():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        response = requests.get(url, timeout=10)
        data = response.json()
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return float(price)
    except Exception as e:
        print("Error fetching gold price:", e)
        return None

# === 2. AI SENTIMENT ANALYSIS (Hugging Face) ===
def get_ai_sentiment(text="Gold market sentiment today"):
    try:
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        payload = {"inputs": text}
        response = requests.post("https://api-inference.huggingface.co/models/ProsusAI/finbert", headers=headers, json=payload, timeout=15)
        result = response.json()

        if isinstance(result, list) and len(result) > 0 and "label" in result[0]:
            label = result[0]["label"]
            score = result[0]["score"]
            return f"{label} ({round(score * 100, 2)}%)"
        return "Neutral (AI Uncertain)"
    except Exception as e:
        print("AI sentiment error:", e)
        return "Neutral (Fetch Failed)"

# === 3. TECHNICAL ZONES ===
def get_zones(price):
    if not price:
        return None, None

    # Support / resistance calculation
    buy_zone_low = round(price * 0.995, 2)
    buy_zone_high = round(price * 0.997, 2)
    sell_zone_low = round(price * 1.003, 2)
    sell_zone_high = round(price * 1.005, 2)
    return (buy_zone_low, buy_zone_high), (sell_zone_low, sell_zone_high)

# === 4. PROBABILITY ESTIMATOR ===
def calculate_confidence(sentiment):
    sentiment = sentiment.lower()
    if "positive" in sentiment or "bullish" in sentiment:
        return 85
    elif "negative" in sentiment or "bearish" in sentiment:
        return 85
    else:
        return 60

# === 5. DISCORD EMBED SENDER ===
def send_discord_update(title, description, color=0xFFD700):
    webhook = SyncWebhook.from_url(WEBHOOK_URL)
    embed = Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(TIMEZONE)
    )
    embed.set_footer(text="AI Gold Forecast Bot • Powered by Hasan Ali")
    webhook.send(embed=embed)
    print(f"✅ Sent update: {title}")

# === 6. DAILY FORECAST ===
def send_daily_forecast():
    price = get_gold_price()
    if not price:
        send_discord_update("⚠️ Gold Price Error", "Could not fetch live gold price.")
        return

    buy_zone, sell_zone = get_zones(price)
    ai_sentiment = get_ai_sentiment("Gold market outlook, risk sentiment, and USD strength today.")
    confidence = calculate_confidence(ai_sentiment)

    description = (
        f"**Live Gold Price:** ${price}\n"
        f"**AI Sentiment:** {ai_sentiment}\n"
        f"**Confidence:** {confidence}%\n\n"
        f"💰 **Buy Zone:** {buy_zone[0]} – {buy_zone[1]}\n"
        f"📈 **Sell Zone:** {sell_zone[0]} – {sell_zone[1]}"
    )

    send_discord_update("🏆 Daily Gold Forecast", description)

# === 7. LIVE MONITOR (Every 5 minutes) ===
def monitor_gold():
    print("🔁 Monitoring gold price for trade opportunities...")
    last_signal = None

    while True:
        price = get_gold_price()
        if price:
            buy_zone, sell_zone = get_zones(price)
            ai_sentiment = get_ai_sentiment("Gold market movement and manipulation probability.")
            confidence = calculate_confidence(ai_sentiment)

            if confidence >= 80:
                if buy_zone[0] <= price <= buy_zone[1]:
                    if last_signal != "buy":
                        send_discord_update(
                            "🟢 Gold Entered BUY Zone",
                            f"Price: ${price}\nAI Confidence: {confidence}%\nSentiment: {ai_sentiment}\nSuggested Action: **Consider Long Entries**",
                            color=0x00FF00
                        )
                        last_signal = "buy"
                elif sell_zone[0] <= price <= sell_zone[1]:
                    if last_signal != "sell":
                        send_discord_update(
                            "🔴 Gold Entered SELL Zone",
                            f"Price: ${price}\nAI Confidence: {confidence}%\nSentiment: {ai_sentiment}\nSuggested Action: **Consider Short Entries**",
                            color=0xFF0000
                        )
                        last_signal = "sell"
        time.sleep(300)  # check every 5 minutes

# === 8. SCHEDULER ===
def run_scheduler():
    print("🚀 Gold Forecast AI Bot is live...")
    while True:
        now = datetime.now(TIMEZONE)
        if now.hour == SEND_HOUR and now.minute == 0:
            send_daily_forecast()
            time.sleep(60)
        else:
            time.sleep(20)

# === MAIN ===
if __name__ == "__main__":
    send_daily_forecast()  # Send immediately when deployed
    from threading import Thread
    Thread(target=monitor_gold).start()  # Start background monitoring
    run_scheduler()
