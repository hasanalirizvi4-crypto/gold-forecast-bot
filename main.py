import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime
import threading
from discord_webhook import DiscordWebhook
import pytz
import logging
import flask

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
    return trend, round(confidence, 2), last["price"], last["ema_20"], last["ema_50"]


def detect_potential_zones(prices):
    """Roughly detect potential buy/sell zones using local highs and lows."""
    df = pd.DataFrame(prices, columns=["price"])
    recent = df.tail(50)
    support = recent["price"].min()
    resistance = recent["price"].max()
    return round(support, 2), round(resistance, 2)


def send_discord_message(message):
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK, content=message)
        webhook.execute()
    except Exception as e:
        logging.error(f"❌ Failed to send Discord message: {e}")


# ======================================
# MAIN LOOP
# ======================================
def start_bot():
    logging.info("🚀 Gold AI Tracker started")
    send_discord_message("🤖 **Gold AI Tracker is now LIVE!** Monitoring XAU/USD movements...")

    prices = []
    last_trend = None
    last_summary_date = None
    last_alert_price = None

    while True:
        price = fetch_gold_price()
        if price:
            prices.append(price)
            if len(prices) > 200:
                prices.pop(0)

            if len(prices) > 50:
                trend, confidence, current_price, ema20, ema50 = calculate_indicators(prices)

                # Instant signal alerts
                if (trend != last_trend and (confidence >= 60 or confidence <= 40)):
                    message = (
                        f"💰 **Gold Market Signal (XAU/USD)**\n"
                        f"Price: **${current_price:.2f}**\n"
                        f"Trend: {trend}\n"
                        f"Confidence: **{confidence}%**\n"
                        f"Time: {datetime.now(TIMEZONE).strftime('%I:%M %p %Z')}\n"
                        f"⚙️ Indicators are aligning for a new move!\n"
                        f"*(Educational insight — not financial advice)*"
                    )
                    send_discord_message(message)
                    last_trend = trend

                # Big move alerts (±1%)
                if last_alert_price:
                    change = ((price - last_alert_price) / last_alert_price) * 100
                    if abs(change) >= 1:
                        move_type = "🚀 Spike Up!" if change > 0 else "⚠️ Sharp Drop!"
                        send_discord_message(
                            f"{move_type}\n💰 **Gold moved {change:.2f}%** to **${price:.2f}**!\n"
                            f"Stay alert for possible volatility ⚡"
                        )
                        last_alert_price = price
                else:
                    last_alert_price = price

            logging.info(f"💰 Updated Gold Price: {price}")

        else:
            logging.warning("⚠️ Could not fetch gold price from GoldAPI.")

        # Daily summary at 12 AM PKT
        now = datetime.now(TIMEZONE)
        if now.hour == 0 and (last_summary_date is None or now.date() != last_summary_date):
            support, resistance = detect_potential_zones(prices)
            summary = (
                f"🕛 **Daily Gold Market Summary ({now.strftime('%d %b %Y')})**\n"
                f"- Closing Price: **${price:.2f if price else 'N/A'}**\n"
                f"- Key Support: **${support}** | Resistance: **${resistance}**\n"
                f"- Last Trend: {last_trend or 'N/A'}\n"
                f"- AI Outlook: Expect activity near these zones tomorrow.\n"
                f"*(AI-Generated for educational purposes only.)*"
            )
            send_discord_message(summary)
            last_summary_date = now.date()

        time.sleep(UPDATE_INTERVAL)


# ======================================
# FLASK SERVER FOR RENDER
# ======================================
app = flask.Flask(__name__)

@app.route('/')
def home():
    return "✅ Gold AI Tracker is running!"

if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    app.run(host="0.0.0.0", port=10000)
