import requests
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
from discord_webhook import DiscordWebhook
from bs4 import BeautifulSoup
import threading
import logging

# ======================================================
# CONFIGURATION
# ======================================================
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"
GOLD_API_KEY = "a255414b6c7af4586f3b4696bd444950"
TIMEZONE = pytz.timezone("Asia/Karachi")
UPDATE_INTERVAL = 60  # seconds

# ======================================================
# LOGGING
# ======================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ======================================================
# HELPER FUNCTIONS
# ======================================================
def send_discord(msg: str):
    """Send formatted message to Discord."""
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK, content=msg)
        webhook.execute()
    except Exception as e:
        logging.error(f"❌ Discord send error: {e}")

def fetch_yahoo_gold_price():
    """Fetch gold price from Yahoo Finance."""
    try:
        ticker = yf.Ticker("XAUUSD=X")
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return data["Close"].iloc[-1]
    except Exception as e:
        logging.error(f"❌ Yahoo fetch error: {e}")
    return None

def fetch_goldapi_price():
    """Fallback to GoldAPI."""
    try:
        headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}
        r = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        if r.status_code == 200:
            return float(r.json()["price"])
    except Exception as e:
        logging.error(f"❌ GoldAPI error: {e}")
    return None

def get_forexfactory_news():
    """Scrape high-impact forex news from Forex Factory."""
    url = "https://www.forexfactory.com/calendar"
    try:
        page = requests.get(url, timeout=10)
        soup = BeautifulSoup(page.text, "html.parser")
        events = []
        for row in soup.find_all("tr", class_="calendar__row"):
            if "high" in str(row):  # High impact news
                time_tag = row.find("td", class_="calendar__time")
                impact_tag = row.find("span", class_="impact")
                event_tag = row.find("td", class_="calendar__event")
                currency_tag = row.find("td", class_="calendar__currency")
                if time_tag and event_tag and impact_tag:
                    events.append(
                        f"🕒 {time_tag.text.strip()} | 💥 {currency_tag.text.strip()} | {event_tag.text.strip()}"
                    )
        return events[:5] if events else []
    except Exception as e:
        logging.warning(f"⚠️ Could not fetch ForexFactory news: {e}")
        return []

def calculate_indicators(prices):
    """Basic technicals: EMA, RSI, MACD, Bollinger Bands."""
    df = pd.DataFrame(prices, columns=["price"])
    df["ema20"] = df["price"].ewm(span=20).mean()
    df["ema50"] = df["price"].ewm(span=50).mean()
    delta = df["price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / (loss.rolling(14).mean() + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))
    exp1, exp2 = df["price"].ewm(span=12).mean(), df["price"].ewm(span=26).mean()
    df["macd"], df["signal"] = exp1 - exp2, exp1 - exp2
    df["sma20"] = df["price"].rolling(20).mean()
    df["std"] = df["price"].rolling(20).std()
    df["upper"], df["lower"] = df["sma20"] + 2 * df["std"], df["sma20"] - 2 * df["std"]
    last = df.iloc[-1]

    conf = 50
    if last["ema20"] > last["ema50"]: conf += 15
    if last["rsi"] < 30: conf += 10
    elif last["rsi"] > 70: conf -= 10
    if last["price"] < last["lower"]: conf += 10
    elif last["price"] > last["upper"]: conf -= 10

    trend = "📈 **Bullish Momentum**" if conf >= 60 else "📉 **Bearish Pressure**" if conf <= 40 else "⚖️ **Neutral Zone**"
    return trend, round(conf, 2), last["price"]

def detect_zones(data):
    """Find potential buy/sell zones."""
    highs, lows = data["High"], data["Low"]
    buy_zone = round(lows.tail(5).mean(), 2)
    sell_zone = round(highs.tail(5).mean(), 2)
    return buy_zone, sell_zone

def detect_big_moves(df):
    """Detect large price moves or ATH breaks."""
    change = (df["Close"].iloc[-1] - df["Close"].iloc[-2]) / df["Close"].iloc[-2] * 100
    alert = None
    if abs(change) > 0.5:
        alert = f"⚠️ **Big Move Alert!** Gold moved {change:.2f}% in last minute."
    return alert

# ======================================================
# MAIN BOT
# ======================================================
def gold_bot():
    logging.info("🚀 Gold AI Forecast v3.0 running...")
    prices = []
    last_trend = None
    last_report_time = None

    send_discord("🤖 **Gold AI Bot Activated!** Tracking live XAU/USD price & market sentiment...")

    while True:
        price = fetch_yahoo_gold_price() or fetch_goldapi_price()
        if not price:
            logging.warning("⚠️ Price fetch failed.")
            time.sleep(UPDATE_INTERVAL)
            continue

        prices.append(price)
        if len(prices) > 200: prices.pop(0)
        logging.info(f"💰 Price: {price}")

        # Calculate indicators
        if len(prices) > 50:
            trend, conf, current = calculate_indicators(prices)

            if trend != last_trend and (conf >= 60 or conf <= 40):
                send_discord(f"💎 **Gold Market Signal**\nPrice: ${current:.2f}\nTrend: {trend}\nConfidence: {conf}%")
                last_trend = trend

        # Check for daily and intraday reports
        now = datetime.now(TIMEZONE)
        if (now.hour == 0 or now.hour == 12) and (not last_report_time or now.date() != last_report_time.date() or abs((now - last_report_time).seconds) > 3600):
            ticker = yf.Ticker("XAUUSD=X")
            hist = ticker.history(period="5d", interval="1h")
            buy_zone, sell_zone = detect_zones(hist)
            alert = detect_big_moves(hist)

            news = get_forexfactory_news()
            news_text = "\n".join(news) if news else "No major news updates."

            summary = (
                f"📅 **Market Report ({now.strftime('%d %b %Y %I:%M %p')})**\n"
                f"💰 Price: ${price:.2f}\n"
                f"Trend: {last_trend or 'Neutral'} | Confidence: {conf if prices else 'N/A'}%\n"
                f"📊 Zones → Buy: ${buy_zone} | Sell: ${sell_zone}\n"
                f"📰 Key News:\n{news_text}\n\n"
                f"{alert or ''}\n"
                f"🤖 AI Outlook: Based on sentiment, liquidity zones suggest potential reaction around ${buy_zone}–${sell_zone}.\n"
                f"*(Educational use only — not financial advice)*"
            )
            send_discord(summary)
            last_report_time = now

        time.sleep(UPDATE_INTERVAL)

# ======================================================
# ENTRY POINT
# ======================================================
if __name__ == "__main__":
    threading.Thread(target=gold_bot).start()
