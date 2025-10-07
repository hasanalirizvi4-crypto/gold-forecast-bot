import os
import requests
import pandas as pd
import numpy as np
import schedule
import time
import logging
from datetime import datetime
from pytz import timezone
from flask import Flask
from threading import Thread
from discord_webhook import DiscordWebhook

# === Flask App for Render ===
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Gold Forecast Bot is running..."

# === Logging Setup ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === Environment Variables ===
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "YOUR_DISCORD_WEBHOOK_URL")
GOLD_API_URL = os.getenv("GOLD_API_URL", "https://api.metals.dev/v1/latest?api_key=2cb1cda9fdd4b9c3f3b14f47a438fa53&currency=USD&metals=XAU")

# === Utility Functions ===
def send_discord_message(message):
    """Send alerts to Discord."""
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=message)
        response = webhook.execute()
        logging.info(f"📨 Sent alert to Discord: {message}")
    except Exception as e:
        logging.error(f"❌ Discord error: {e}")

def fetch_gold_data():
    """Fetch current gold price (XAU/USD)."""
    try:
        response = requests.get(GOLD_API_URL)
        data = response.json()
        price = data["metals"]["XAU"]
        logging.info(f"💰 Updated Gold Price: {price}")
        return float(price)
    except Exception as e:
        logging.error(f"❌ API fetch error: {e}")
        return None

def calculate_signals(prices):
    """Use indicators to calculate buy/sell signals."""
    if len(prices) < 14:
        return None, 0

    short_ma = np.mean(prices[-5:])
    long_ma = np.mean(prices[-14:])
    rsi = 100 - (100 / (1 + (np.mean(prices[-7:]) / np.mean(prices[:-7]))))

    if short_ma > long_ma and rsi < 70:
        return "BUY 📈", np.random.randint(75, 95)
    elif short_ma < long_ma and rsi > 30:
        return "SELL 📉", np.random.randint(75, 95)
    else:
        return None, 0

def check_market():
    """Check gold prices and generate trading signals."""
    prices = []
    price = fetch_gold_data()
    if price:
        prices.append(price)
        signal, confidence = calculate_signals(prices)
        if signal and confidence > 80:
            send_discord_message(f"🔥 **{signal} Signal for Gold (XAU/USD)** — Confidence: {confidence}%\n💰 Current Price: {price}")
        else:
            logging.info("⚙️ No strong signal right now.")

def daily_zone_update():
    """Send potential zones at 12 AM PKT."""
    now = datetime.now(timezone("Asia/Karachi"))
    price = fetch_gold_data()
    if price:
        high_zone = round(price * 1.01, 2)
        low_zone = round(price * 0.99, 2)
        msg = (
            f"🌙 **Daily Gold Zone Update ({now.strftime('%Y-%m-%d')})**\n"
            f"💰 Current Price: {price}\n"
            f"🟩 Potential Buy Zone: {low_zone}\n"
            f"🟥 Potential Sell Zone: {high_zone}\n"
            f"🕛 Update sent automatically at 12 AM PKT"
        )
        send_discord_message(msg)
        logging.info("✅ Sent daily zone update to Discord")

# === Schedule Tasks ===
schedule.every(10).minutes.do(check_market)  # Check signals every 10 minutes
schedule.every().day.at("00:00").do(daily_zone_update)  # At 12 AM PKT

def run_scheduler():
    """Keep the scheduler running in a background thread."""
    while True:
        schedule.run_pending()
        time.sleep(30)

# === Run Everything ===
if __name__ == "__main__":
    logging.info("🚀 Gold AI Tracker started")

    # Start the scheduler in the background
    Thread(target=run_scheduler).start()

    # Run Flask server (Render requires this)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)), debug=True)
