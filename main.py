import yfinance as yf
import requests
import datetime
import numpy as np
import pandas as pd
import time
import schedule

DISCORD_WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL"
METALS_API_KEY = "a255414b6c7af4586f3b4696bd444950"
ALL_TIME_HIGH = 2430.50
PRICE_CHANGE_THRESHOLD = 1.0

# === Helper Functions ===

def send_alert(title, message, color=0xFFD700):
    data = {
        "username": "GoldBot 🦅",
        "embeds": [{
            "title": title,
            "description": message,
            "color": color,
            "footer": {"text": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        }]
    }
    r = requests.post(DISCORD_WEBHOOK_URL, json=data)
    if r.status_code not in [200, 204]:
        print("Webhook Error:", r.text)

def get_gold_price():
    tickers = ["XAUUSD=X", "GC=F"]
    for t in tickers:
        try:
            data = yf.Ticker(t)
            df = data.history(period="1d", interval="1m")
            if not df.empty:
                price = df["Close"].iloc[-1]
                if price > 10:
                    return float(price)
        except Exception as e:
            print("Yahoo error:", e)
    try:
        url = f"https://metals-api.com/api/latest?access_key={METALS_API_KEY}&base=USD&symbols=XAU"
        resp = requests.get(url).json()
        return 1 / resp["rates"]["XAU"]
    except:
        return None

# === Indicators ===
def calculate_indicators(df):
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    delta = df["Close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(14).mean()
    avg_loss = pd.Series(loss).rolling(14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    df["BB_MID"] = df["Close"].rolling(20).mean()
    df["BB_STD"] = df["Close"].rolling(20).std()
    df["BB_UPPER"] = df["BB_MID"] + 2 * df["BB_STD"]
    df["BB_LOWER"] = df["BB_MID"] - 2 * df["BB_STD"]

    return df

def indicator_alignment(df):
    last = df.iloc[-1]
    alignments = []
    if last["RSI"] > 55: alignments.append("RSI Bullish")
    elif last["RSI"] < 45: alignments.append("RSI Bearish")

    if last["MACD"] > last["Signal"]: alignments.append("MACD Bullish")
    else: alignments.append("MACD Bearish")

    for ma in ["MA20", "MA50", "MA200"]:
        if last["Close"] > last[ma]: alignments.append(f"{ma} Bullish")
        else: alignments.append(f"{ma} Bearish")

    if last["Close"] <= last["BB_LOWER"]: alignments.append("Near Lower BB (Buy Zone)")
    elif last["Close"] >= last["BB_UPPER"]: alignments.append("Near Upper BB (Sell Zone)")

    bullish = len([x for x in alignments if "Bullish" in x or "Buy" in x])
    bearish = len([x for x in alignments if "Bearish" in x or "Sell" in x])

    bias = "🟢 Bullish" if bullish > bearish + 1 else "🔴 Bearish" if bearish > bullish + 1 else "🟡 Neutral"
    return alignments, bias

# === News Impact ===
def get_news_impact():
    try:
        resp = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        data = resp.json()
        today = datetime.date.today().strftime("%Y-%m-%d")
        usd_news = [n for n in data if today in n["date"] and "USD" in n["country"] and n["impact"] == "High"]
        if not usd_news:
            return 0, "No major USD news today."

        headlines = "\n".join([f"📰 {n['title']} — {n['impact']}" for n in usd_news])
        bias = -20 if "positive" in str(usd_news).lower() else 20
        return bias, headlines
    except:
        return 0, "Could not fetch ForexFactory news."

# === Main Market Logic ===
def analyze_market():
    df = yf.Ticker("XAUUSD=X").history(period="5d", interval="1h")
    df = calculate_indicators(df)
    price = df["Close"].iloc[-1]
    prev_high, prev_low = df["High"].iloc[-2], df["Low"].iloc[-2]

    indicators, bias = indicator_alignment(df)
    news_bias, news_summary = get_news_impact()

    confidence = 50
    if "Bullish" in bias: confidence += 25
    elif "Bearish" in bias: confidence -= 25
    confidence += news_bias
    confidence = max(0, min(100, confidence))

    message = (
        f"💰 **Gold Price:** ${price:.2f}\n"
        f"📊 **Market Bias:** {bias}\n"
        f"🔥 **Trade Confidence:** {confidence}%\n"
        f"🧭 **Indicators:**\n" + "\n".join([f"• {x}" for x in indicators]) + "\n\n"
        f"📰 **News Impact:**\n{news_summary}\n\n"
        f"📉 **Prev Day Low:** {prev_low:.2f} | **High:** {prev_high:.2f}"
    )

    color = 0x00FF00 if "Bullish" in bias else (0xFF0000 if "Bearish" in bias else 0xFFFF00)
    send_alert("📈 Gold Market Update", message, color=color)

# === Scheduler ===
def run_bot():
    send_alert("🤖 GoldBot Live", "System is online and monitoring gold markets 24/7 🌍", color=0x00FFFF)
    analyze_market()
    schedule.every().hour.do(analyze_market)
    schedule.every().day.at("00:00").do(analyze_market)
    schedule.every().day.at("12:00").do(analyze_market)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    run_bot()
