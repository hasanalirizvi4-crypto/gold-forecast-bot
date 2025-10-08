import requests
import yfinance as yf
import pandas as pd
import numpy as np
import time
import datetime
import threading
import pytz
import json
import logging

# ======================================
# CONFIG
# ======================================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"
GOLDAPI_KEY = "goldapi-favtsmgcmdotp-io"
UPDATE_INTERVAL = 120  # seconds
TIMEZONE = pytz.timezone("Asia/Karachi")

# ======================================
# LOGGING
# ======================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ======================================
# DISCORD EMBED ALERT
# ======================================
def send_alert(title, message, color=0xFFD700):
    """Send an embed message to Discord via webhook."""
    try:
        data = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                    "footer": {
                        "text": "Gold AI Forecast v3.1",
                        "icon_url": "https://cdn-icons-png.flaticon.com/512/3876/3876066.png"
                    },
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
            ]
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(DISCORD_WEBHOOK_URL, headers=headers, data=json.dumps(data))

        if response.status_code != 204:
            logging.warning(f"⚠️ Webhook error {response.status_code}: {response.text}")
    except Exception as e:
        logging.error(f"❌ Discord alert failed: {e}")

# ======================================
# PRICE FETCHERS
# ======================================
def fetch_yahoo_price():
    """Fetch latest gold price from Yahoo Finance."""
    try:
        ticker = yf.Ticker("GC=F")  # Gold futures
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception as e:
        logging.error(f"❌ Yahoo fetch error: {e}")
    return None

def fetch_goldapi_price():
    """Fetch gold price from GoldAPI as backup."""
    try:
        headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}
        url = "https://www.goldapi.io/api/XAU/USD"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return float(data["price"])
        else:
            logging.warning(f"⚠️ GoldAPI returned status {r.status_code}")
    except Exception as e:
        logging.error(f"❌ GoldAPI error: {e}")
    return None

# ======================================
# TECHNICAL INDICATORS
# ======================================
def calculate_indicators(prices):
    df = pd.DataFrame(prices, columns=["price"])
    df["ema_20"] = df["price"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["price"].ewm(span=50, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + df["price"].diff().clip(lower=0).rolling(14).mean() /
                              (df["price"].diff().clip(upper=0).abs().rolling(14).mean() + 1e-9)))
    exp1 = df["price"].ewm(span=12, adjust=False).mean()
    exp2 = df["price"].ewm(span=26, adjust=False).mean()
    df["macd"] = exp1 - exp2
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["sma_20"] = df["price"].rolling(20).mean()
    df["upper_band"] = df["sma_20"] + 2 * df["price"].rolling(20).std()
    df["lower_band"] = df["sma_20"] - 2 * df["price"].rolling(20).std()
    return df

# ======================================
# NEWS SCRAPER (ForexFactory)
# ======================================
def get_forex_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            events = r.json()
            today = datetime.datetime.now(TIMEZONE).date()
            today_events = [e for e in events if e.get("impact") in ["High", "Medium"] and
                            datetime.datetime.fromtimestamp(int(e["timestamp"])).date() == today]
            if not today_events:
                return "📰 No major scheduled news impacting gold today."
            msg = "**Today's High-Impact Events:**\n"
            for e in today_events[:5]:
                impact = "🔴" if e["impact"] == "High" else "🟠"
                msg += f"{impact} **{e['title']}** at {e['time']} ({e['country']})\n"
            return msg
        else:
            return "⚠️ Could not fetch news data."
    except Exception as e:
        return f"❌ Error fetching ForexFactory data: {e}"

# ======================================
# BOT MAIN LOOP
# ======================================
def start_bot():
    send_alert("🤖 Gold AI Bot Activated", "Bot is now live and monitoring markets!", 0xFFD700)
    logging.info("🚀 Gold AI Forecast v3.1 running...")

    prices = []
    ath = 0
    last_trend = None
    last_summary_time = None
    last_news_time = None

    while True:
        price = fetch_yahoo_price() or fetch_goldapi_price()
        if not price:
            logging.warning("⚠️ Price fetch failed.")
            time.sleep(UPDATE_INTERVAL)
            continue

        prices.append(price)
        if len(prices) > 300:
            prices.pop(0)

        df = calculate_indicators(prices)
        last = df.iloc[-1]

        # Trend logic
        confidence = 50
        if last["ema_20"] > last["ema_50"]:
            confidence += 15
        if last["rsi"] < 30:
            confidence += 10
        if last["macd"] > last["signal"]:
            confidence += 10

        trend = "📈 Bullish" if confidence >= 60 else "📉 Bearish" if confidence <= 40 else "⚖️ Neutral"
        if trend != last_trend:
            send_alert("💹 Market Update",
                       f"**Trend:** {trend}\n**Price:** ${price:.2f}\n**Confidence:** {confidence}%",
                       0xFFD700)
            last_trend = trend

        # All-time high/low alerts
        if price > ath:
            ath = price
            send_alert("🚀 All-Time High Alert!",
                       f"Gold just hit a new all-time high at **${price:.2f}** 🏆\nWatch for potential pullbacks or liquidity hunts!",
                       0x00FF00)

        if len(prices) >= 2 and (prices[-1] - prices[-2]) / prices[-2] * 100 <= -1.5:
            send_alert("⚠️ Sudden Drop Detected!",
                       f"Gold dropped sharply to **${price:.2f}** in the last minute! Possible liquidity sweep or reaction to news.",
                       0xFF0000)

        # 12 AM + 12 PM News & Analysis
        now = datetime.datetime.now(TIMEZONE)
        if now.hour in [0, 12] and (not last_news_time or last_news_time.date() != now.date() or
                                    (last_news_time.hour != now.hour)):
            news = get_forex_news()
            send_alert("📰 Gold Market News Summary",
                       f"{news}\n\nAI Outlook: {trend} bias with confidence {confidence}%",
                       0x1E90FF)
            last_news_time = now

        time.sleep(UPDATE_INTERVAL)

# ======================================
# RUN
# ======================================
if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
