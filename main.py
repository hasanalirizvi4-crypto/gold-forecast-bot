import yfinance as yf
import requests
import datetime
import numpy as np
import pandas as pd
import time
import schedule

DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147584167055464/thHmNTy5nncm4Dwe4GeZ5hXEh0p8ptuw0n6d1TzBdsufFwuo6Y3FViGfHJjwtMeBAbvk"
METALS_API_KEY = "a255414b6c7af4586f3b4696bd444950"
ALL_TIME_HIGH = 2430.50
PRICE_CHANGE_THRESHOLD = 1.0  # % change alert threshold

last_price = None  # Track previous price globally


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


# === Spot Gold Price (Accurate) ===

def get_gold_price():
    """
    Returns the latest spot gold price (XAU/USD) with multiple fallbacks.
    Priority:
    1. Metals-API (live spot)
    2. Yahoo Finance backup
    3. GoldAPI fallback
    """

    # --- 1. Metals API ---
    try:
        url = f"https://metals-api.com/api/latest?access_key={METALS_API_KEY}&base=USD&symbols=XAU"
        resp = requests.get(url, timeout=5).json()
        if "rates" in resp and "XAU" in resp["rates"]:
            price = 1 / resp["rates"]["XAU"]
            if price > 10:
                return round(price, 2)
    except Exception as e:
        print("Metals API error:", e)

    # --- 2. Yahoo Finance ---
    try:
        data = yf.Ticker("XAUUSD=X")
        df = data.history(period="1d", interval="1m")
        if not df.empty:
            price = df["Close"].iloc[-1]
            if price > 10:
                return round(float(price), 2)
    except Exception as e:
        print("Yahoo Finance error:", e)

    # --- 3. GoldAPI fallback ---
    try:
        resp = requests.get(
            "https://www.goldapi.io/api/XAU/USD",
            headers={"x-access-token": "goldapi-favtsmgcmdotp-io"},
            timeout=5
        )
        data = resp.json()
        if "price" in data and data["price"] > 10:
            return round(data["price"], 2)
    except Exception as e:
        print("GoldAPI fallback error:", e)

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
    if last["RSI"] > 55:
        alignments.append("RSI Bullish")
    elif last["RSI"] < 45:
        alignments.append("RSI Bearish")

    if last["MACD"] > last["Signal"]:
        alignments.append("MACD Bullish")
    else:
        alignments.append("MACD Bearish")

    for ma in ["MA20", "MA50", "MA200"]:
        if last["Close"] > last[ma]:
            alignments.append(f"{ma} Bullish")
        else:
            alignments.append(f"{ma} Bearish")

    if last["Close"] <= last["BB_LOWER"]:
        alignments.append("Near Lower BB (Buy Zone)")
    elif last["Close"] >= last["BB_UPPER"]:
        alignments.append("Near Upper BB (Sell Zone)")

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


# === Market Analysis & Alerts ===
def analyze_market():
    global last_price

    df = yf.Ticker("XAUUSD=X").history(period="5d", interval="1h")
    df = calculate_indicators(df)

    spot_price = get_gold_price()
    if spot_price is None:
        send_alert("⚠️ GoldBot Warning", "Unable to fetch live spot gold price.", color=0xFF0000)
        return

    # --- Price Alerts ---
    if last_price:
        pct_change = ((spot_price - last_price) / last_price) * 100
        if abs(pct_change) >= PRICE_CHANGE_THRESHOLD:
            direction = "📈 UP" if pct_change > 0 else "📉 DOWN"
            send_alert(
                f"💰 Gold Price Alert — {direction}",
                f"Gold moved {pct_change:.2f}% since last check.\nCurrent: **${spot_price:.2f}** | Prev: ${last_price:.2f}",
                color=0x00FF00 if pct_change > 0 else 0xFF0000
            )

    if spot_price >= ALL_TIME_HIGH:
        send_alert(
            "🚀 All-Time High Alert!",
            f"Gold just hit **${spot_price:.2f}**, breaking previous ATH of ${ALL_TIME_HIGH}!",
            color=0xFFD700
        )

    last_price = spot_price

    prev_high, prev_low = df["High"].iloc[-2], df["Low"].iloc[-2]
    indicators, bias = indicator_alignment(df)
    news_bias, news_summary = get_news_impact()

    confidence = 50
    if "Bullish" in bias:
        confidence += 25
    elif "Bearish" in bias:
        confidence -= 25
    confidence += news_bias
    confidence = max(0, min(100, confidence))

    message = (
        f"💰 **Spot Gold Price (Live):** ${spot_price:.2f}\n"
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
    send_alert("🤖 GoldBot Live", "System is online and monitoring spot gold markets 24/7 🌍", color=0x00FFFF)
    analyze_market()
    schedule.every().hour.do(analyze_market)
    schedule.every().day.at("00:00").do(analyze_market)
    schedule.every().day.at("12:00").do(analyze_market)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_bot()
