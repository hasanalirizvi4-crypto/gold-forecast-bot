import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime
import threading
from discord_webhook import DiscordWebhook
import pytz
import logging
from flask import Flask

# ======================================
# CONFIGURATION
# ======================================
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"
GOLD_API_KEY = "goldapi-favtsmgcmdotp-io"
UPDATE_INTERVAL = 60  # seconds
TIMEZONE = pytz.timezone("Asia/Karachi")

# ======================================
# LOGGING
# ======================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ======================================
# FUNCTIONS
# ======================================

def fetch_gold_price():
    """Fetch latest XAU/USD price from GoldAPI."""
    try:
        headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}
        url = "https://www.goldapi.io/api/XAU/USD"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return float(data["price"])
        else:
            logging.warning(f"⚠️ GoldAPI returned status {r.status_code}")
            return None
    except Exception as e:
        logging.error(f"❌ Error fetching gold price: {e}")
        return None


def calculate_indicators(prices):
    """Compute EMA, RSI, MACD, Bollinger Bands, and derive confidence score."""
    df = pd.DataFrame(prices, columns=["price"])
    df["ema_20"] = df["price"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["price"].ewm(span=50, adjust=False).mean()

    delta = df["price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    exp1 = df["price"].ewm(span=12, adjust=False).mean()
    exp2 = df["price"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    df["sma_20"] = df["price"].rolling(window=20).mean()
    df["stddev"] = df["price"].rolling(window=20).std()
    df["upper_band"] = df["sma_20"] + (df["stddev"] * 2)
    df["lower_band"] = df["sma_20"] - (df["stddev"] * 2)

    last = df.iloc[-1]
    confidence = 50  # baseline

    if last["ema_20"] > last["ema_50"]:
        confidence += 15
    else:
        confidence -= 15
    if last["rsi"] > 70:
        confidence -= 10
    elif last["rsi"] < 30:
        confidence += 10
    if last["macd"] > last["signal"]:
        confidence += 10
    else:
        confidence -= 10
    if last["price"] < last["lower_band"]:
        confidence += 10
    elif last["price"] > last["upper_band"]:
        confidence -= 10

    trend = "📈 Bullish Momentum" if confidence >= 60 else "📉 Bearish Pressure" if confidence <= 40 else "⚖️ Neutral Zone"
    return trend, round(confidence, 2), last["price"], df


def identify_zones(df):
    """Identify potential buy/sell zones (support/resistance)."""
    recent = df["price"].tail(100)
    low_zone = recent.min()
    high_zone = recent.max()
    return low_zone, high_zone


def send_discord_message(message):
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK, content=message)
        webhook.execute()
    except Exception as e:
        logging.error(f"❌ Failed to send Discord message: {e}")


# ======================================
# MAIN BOT LOOP
# ======================================
def start_bot():
    logging.info("🚀 Gold AI Tracker started")
    prices = []
    last_trend = None
    last_summary_time = datetime.now(TIMEZONE).date()

    while True:
        price = fetch_gold_price()
        if price:
            prices.append(price)
            if len(prices) > 200:
                prices.pop(0)

            if len(prices) > 50:
                trend, confidence, current_price, df = calculate_indicators(prices)
                low_zone, high_zone = identify_zones(df)

                if trend != last_trend and (confidence >= 60 or confidence <= 40):
                    message = (
                        f"💰 **Gold Market Update (XAU/USD)**\n"
                        f"Price: **${current_price:.2f}**\n"
                        f"Trend: {trend}\n"
                        f"Confidence: **{confidence}%**\n"
                        f"📊 Buy Zone: ~${low_zone:.2f}\n"
                        f"📉 Sell Zone: ~${high_zone:.2f}\n"
                        f"🕒 Time: {datetime.now(TIMEZONE).strftime('%I:%M %p %Z')}\n"
                        f"⚙️ Indicators aligned — potential opportunity detected.\n"
                        f"*(Educational insight — not financial advice)*"
                    )
                    send_discord_message(message)
                    last_trend = trend

            logging.info(f"💰 Updated Gold Price: {price}")

        else:
            logging.warning("⚠️ Could not fetch gold price from GoldAPI.")

        # Daily Summary at 12 AM PKT
        now = datetime.now(TIMEZONE)
        if now.hour == 0 and now.date() != last_summary_time:
            if len(prices) > 50:
                _, _, current_price, df = calculate_indicators(prices)
                low_zone, high_zone = identify_zones(df)

                summary = (
                    f"🕛 **Daily Market Summary ({now.strftime('%d %b %Y')})**\n"
                    f"- Closing Price: ${current_price:.2f}\n"
                    f"- Last Trend: {last_trend or 'N/A'}\n"
                    f"- Potential Buy Zone: ${low_zone:.2f}\n"
                    f"- Potential Sell Zone: ${high_zone:.2f}\n"
                    f"- AI Observation: Market showed {last_trend or 'neutral'} tendencies.\n"
                    f"⚠️ Watch these zones tomorrow for possible reactions.\n"
                    f"*(AI-generated analytical insight only)*"
                )
                send_discord_message(summary)
                last_summary_time = now.date()

        time.sleep(UPDATE_INTERVAL)


# ======================================
# FLASK APP TO KEEP RENDER SERVICE LIVE
# ======================================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Gold AI Tracker is running!"

if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    app.run(host="0.0.0.0", port=10000)
