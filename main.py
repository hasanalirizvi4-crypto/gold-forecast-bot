import time
import threading
import datetime
import yfinance as yf
import pandas as pd
import requests
from flask import Flask
from discord_webhook import DiscordWebhook, DiscordEmbed
from bs4 import BeautifulSoup
import schedule

# ==========================
# CONFIGURATION
# ==========================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/your-current-webhook"
BACKUP_API = "https://commodities-api.com/api/latest?access_key=your_api_key&base=USD&symbols=XAU"
SYMBOL = "GC=F"  # Gold Futures symbol for Yahoo Finance
FETCH_INTERVAL = 180  # seconds
CACHE_EXPIRY = 120  # seconds

# ==========================
# GLOBALS
# ==========================
app = Flask(__name__)
last_price = None
cached_data = {"time": None, "price": None}
ATH = 2430.0  # Example ATH, update this if needed


# ==========================
# DISCORD ALERT FUNCTION
# ==========================
def send_alert(title, message, color=0xFFD700):
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        embed = DiscordEmbed(title=title, description=message, color=color)
        embed.set_timestamp()
        embed.set_footer(text="Gold AI Forecast v3.1", icon_url="https://cdn-icons-png.flaticon.com/512/3876/3876066.png")
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        print(f"[ERROR] Discord alert failed: {e}")


# ==========================
# PRICE FETCHING
# ==========================
def get_gold_price():
    global cached_data
    now = time.time()
    if cached_data["time"] and (now - cached_data["time"] < CACHE_EXPIRY):
        return cached_data["price"]

    try:
        ticker = yf.Ticker(SYMBOL)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            raise ValueError("Empty data returned from Yahoo.")
        price = float(data["Close"].iloc[-1])
        cached_data = {"time": now, "price": price}
        return price
    except Exception as e:
        print(f"[ERROR] Yahoo fetch error: {e}")
        # Backup
        try:
            res = requests.get(BACKUP_API, timeout=10)
            js = res.json()
            return float(js["data"]["rates"]["XAU"])
        except Exception as e2:
            print(f"[ERROR] Backup API failed: {e2}")
            return None


# ==========================
# LIQUIDITY ZONES
# ==========================
def analyze_liquidity(df):
    high = df["High"].max()
    low = df["Low"].min()
    avg = (high + low) / 2
    return high, low, avg


# ==========================
# FOREX FACTORY NEWS SCRAPER
# ==========================
def fetch_forex_news():
    try:
        url = "https://www.forexfactory.com/"
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select(".calendar__row")
        news_list = []

        for row in rows[:5]:
            impact = row.select_one(".calendar__impact span")
            title = row.select_one(".calendar__event-title")
            currency = row.select_one(".calendar__currency")
            if title and currency and impact:
                news_list.append(f"{currency.text.strip()} | {impact['title']} | {title.text.strip()}")
        return news_list
    except Exception as e:
        print(f"[ERROR] Forex news fetch failed: {e}")
        return []


# ==========================
# ANALYSIS AND ALERT LOGIC
# ==========================
def analyze_and_alert():
    global last_price
    price = get_gold_price()
    if not price:
        print("[WARNING] ⚠️ Price fetch failed.")
        return

    print(f"[INFO] Current Gold Price: {price}")

    # Get last day's data
    ticker = yf.Ticker(SYMBOL)
    hist = ticker.history(period="2d")
    if len(hist) < 2:
        return
    prev_high = hist["High"].iloc[-2]
    prev_low = hist["Low"].iloc[-2]

    # Breakout detection
    if price > ATH:
        send_alert("🚀 NEW ALL-TIME HIGH!", f"Gold has just broken above the ATH at ${ATH:.2f}!\nCurrent Price: **${price:.2f}**")
    elif price < prev_low:
        send_alert("⚠️ New Daily Low", f"Gold just broke below yesterday's low of ${prev_low:.2f}!\nCurrent Price: **${price:.2f}**")
    elif price > prev_high:
        send_alert("📈 New Daily High", f"Gold has broken above yesterday's high of ${prev_high:.2f}!\nCurrent Price: **${price:.2f}**")

    # Liquidity zones
    high, low, avg = analyze_liquidity(hist)
    liquidity_msg = f"💧 **Buy-Side Liquidity:** Above ${high:.2f}\n💧 **Sell-Side Liquidity:** Below ${low:.2f}\n📊 Fair Value Zone: Around ${avg:.2f}"
    send_alert("💧 Liquidity Update", liquidity_msg)

    last_price = price


# ==========================
# DAILY NEWS ALERT
# ==========================
def news_update():
    news = fetch_forex_news()
    if not news:
        send_alert("📰 Daily News Update", "Could not fetch news today.")
        return

    formatted = "\n".join([f"• {n}" for n in news])
    send_alert("📰 Gold Market News Update", f"Here are the top events likely to affect gold today:\n\n{formatted}")


# ==========================
# SCHEDULER
# ==========================
def schedule_jobs():
    send_alert("✅ Bot Live", "Gold AI Forecast Bot v3.1 is now active and tracking markets.")
    analyze_and_alert()
    news_update()
    schedule.every(FETCH_INTERVAL).seconds.do(analyze_and_alert)
    schedule.every().day.at("00:00").do(news_update)
    schedule.every().day.at("12:00").do(news_update)

    while True:
        schedule.run_pending()
        time.sleep(5)


# ==========================
# FLASK APP
# ==========================
@app.route("/")
def home():
    return "🚀 Gold AI Forecast v3.1 is running."

if __name__ == "__main__":
    threading.Thread(target=schedule_jobs, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
