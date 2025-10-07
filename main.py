import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import threading
from discord_webhook import DiscordWebhook
import pytz
import logging

# ======================================
# CONFIGURATION
# ======================================
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"
GOLD_API_KEY = "goldapi-favtsmgcmdotp-io"      # for live XAU/USD price
FINNHUB_API_KEY = "c3b6n2iad3i9vkl5e9lg"        # free candle data API
UPDATE_INTERVAL = 60                            # seconds
TIMEZONE = pytz.timezone("Asia/Karachi")

# ======================================
# LOGGING
# ======================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ======================================
# FETCH FUNCTIONS
# ======================================
def fetch_gold_price():
    """Fetch latest XAU/USD price from GoldAPI."""
    try:
        headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}
        r = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        if r.status_code == 200:
            return float(r.json()["price"])
        else:
            logging.warning(f"⚠️ GoldAPI returned status {r.status_code}")
    except Exception as e:
        logging.error(f"❌ Error fetching gold price: {e}")
    return None


def fetch_candles(symbol="XAUUSD", interval="60"):
    """Fetch 1h or 4h OHLC data from Finnhub."""
    try:
        url = f"https://finnhub.io/api/v1/forex/candle?symbol=OANDA:{symbol}&resolution={interval}&count=200&token={FINNHUB_API_KEY}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data["s"] == "ok":
                df = pd.DataFrame({
                    "time": [datetime.fromtimestamp(t, TIMEZONE) for t in data["t"]],
                    "open": data["o"], "high": data["h"], "low": data["l"], "close": data["c"]
                })
                return df
        logging.warning("⚠️ Could not fetch candles from Finnhub.")
    except Exception as e:
        logging.error(f"❌ Error fetching candle data: {e}")
    return None


# ======================================
# ANALYSIS FUNCTIONS
# ======================================
def calculate_indicators(prices):
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
    confidence = 50

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
    return trend, round(confidence, 2), last["price"]


def detect_zones(df):
    """Detect simple order-block style zones from OHLC data."""
    recent = df.tail(50)
    highs = recent["high"].rolling(window=3, center=True).max()
    lows = recent["low"].rolling(window=3, center=True).min()

    potential_buy = lows.sort_values().head(3).tolist()
    potential_sell = highs.sort_values(ascending=False).head(3).tolist()

    buy_zone = f"{min(potential_buy):.2f} - {max(potential_buy):.2f}" if potential_buy else "N/A"
    sell_zone = f"{min(potential_sell):.2f} - {max(potential_sell):.2f}" if potential_sell else "N/A"
    return buy_zone, sell_zone


# ======================================
# DISCORD FUNCTION
# ======================================
def send_discord_message(msg):
    try:
        DiscordWebhook(url=DISCORD_WEBHOOK, content=msg).execute()
    except Exception as e:
        logging.error(f"❌ Discord send error: {e}")


# ======================================
# MAIN BOT LOOP
# ======================================
def start_bot():
    logging.info("🚀 Gold AI Tracker started")
    prices = []
    last_trend = None
    last_summary_date = None

    while True:
        price = fetch_gold_price()
        if price:
            prices.append(price)
            if len(prices) > 300:
                prices.pop(0)

            if len(prices) > 50:
                trend, confidence, current_price = calculate_indicators(prices)
                if trend != last_trend and (confidence >= 65 or confidence <= 35):
                    message = (
                        f"💰 **Gold Market Alert (XAU/USD)**\n"
                        f"💵 Price: **${current_price:.2f}**\n"
                        f"📊 Trend: {trend}\n"
                        f"🔮 Confidence: **{confidence}%**\n"
                        f"🕐 Time: {datetime.now(TIMEZONE).strftime('%I:%M %p %Z')}\n"
                        f"⚙️ Indicators aligned — potential **{'BUY 🟩' if 'Bullish' in trend else 'SELL 🟥'}** opportunity.\n"
                        f"*(For educational insight only)*"
                    )
                    send_discord_message(message)
                    last_trend = trend

            logging.info(f"💰 Updated Gold Price: {price}")

        # Daily Summary at 12 AM PKT
        now = datetime.now(TIMEZONE)
        if now.hour == 0 and (last_summary_date is None or now.date() != last_summary_date):
            one_hr = fetch_candles("XAUUSD", "60")
            four_hr = fetch_candles("XAUUSD", "240")
            buy_zone_1h, sell_zone_1h = detect_zones(one_hr) if one_hr is not None else ("N/A", "N/A")
            buy_zone_4h, sell_zone_4h = detect_zones(four_hr) if four_hr is not None else ("N/A", "N/A")

            summary = (
                f"🕛 **Daily Gold Report ({now.strftime('%d %b %Y')})**\n"
                f"💰 Closing Price: **${price:.2f if price else 'N/A'}**\n"
                f"📈 Last Trend: {last_trend or 'N/A'}\n"
                f"🟩 Potential Buy Zone (1H): {buy_zone_1h}\n"
                f"🟥 Potential Sell Zone (1H): {sell_zone_1h}\n"
                f"🟩 Potential Buy Zone (4H): {buy_zone_4h}\n"
                f"🟥 Potential Sell Zone (4H): {sell_zone_4h}\n"
                f"🤖 AI Observation: Market may show {'bullish' if 'Bullish' in (last_trend or '') else 'bearish' if 'Bearish' in (last_trend or '') else 'neutral'} tone tomorrow.\n"
                f"⚠️ Watch news for manipulation signals.\n"
                f"*(AI-generated summary for analytical purposes)*"
            )
            send_discord_message(summary)
            last_summary_date = now.date()

        time.sleep(UPDATE_INTERVAL)


# ======================================
# START
# ======================================
if __name__ == "__main__":
    threading.Thread(target=start_bot).start()

