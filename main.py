import os
import requests
import schedule
import time
import threading
from datetime import datetime
from discord_webhook import DiscordWebhook
from flask import Flask, jsonify
import statistics

# -----------------------------
# CONFIGURATION
# -----------------------------
DISCORD_WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL"
API_URL = "https://api.metalpriceapi.com/v1/latest"
API_KEY = "YOUR_API_KEY"  # Replace with your actual MetalPriceAPI key

app = Flask(__name__)

# -----------------------------
# FETCH GOLD PRICE SAFELY
# -----------------------------
def fetch_gold_price():
    try:
        response = requests.get(f"{API_URL}?api_key={API_KEY}&base=USD&currencies=XAU")
        data = response.json()
        print("🔍 API Response:", data)

        if "rates" in data and "XAU" in data["rates"]:
            return data["rates"]["XAU"]
        else:
            print("⚠️ Unexpected API response format.")
            return None
    except Exception as e:
        print("❌ API fetch error:", e)
        return None


# -----------------------------
# SIMPLE INDICATOR-BASED SIGNAL
# -----------------------------
def analyze_indicators():
    price = fetch_gold_price()
    if not price:
        return None

    # Simulated multi-timeframe analysis
    hourly_trend = price * 1.002
    daily_trend = price * 1.003
    weekly_trend = price * 0.998

    confidence = 0
    if hourly_trend > price:
        confidence += 30
    if daily_trend > price:
        confidence += 40
    if weekly_trend > price:
        confidence += 30

    confidence_level = "🟢 Strong Buy" if confidence >= 80 else "🟡 Neutral" if confidence >= 50 else "🔴 Sell"

    analysis = {
        "price": round(price, 2),
        "confidence": confidence,
        "signal": confidence_level,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    print("📊 Analysis:", analysis)
    return analysis


# -----------------------------
# SEND ALERT TO DISCORD
# -----------------------------
def send_discord_alert(message: str):
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=message)
        webhook.execute()
        print("✅ Sent alert to Discord.")
    except Exception as e:
        print("❌ Failed to send Discord alert:", e)


# -----------------------------
# INTRADAY FORECAST REPORT
# -----------------------------
def generate_intraday_report():
    gold_price = fetch_gold_price()
    if not gold_price:
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "report": "⚠️ Unable to fetch gold price data. Please check API or connection."
        }

    # Simulate hourly fluctuations
    simulated_prices = [gold_price * (1 + i * 0.0015) for i in range(-3, 4)]
    avg_price = statistics.mean(simulated_prices)
    recent_trend = simulated_prices[-1] - simulated_prices[0]

    if recent_trend > 0:
        outlook = "📈 Bullish tone — Gold may continue rising today."
    elif recent_trend < 0:
        outlook = "📉 Bearish pressure — Some decline possible today."
    else:
        outlook = "⚖️ Neutral — Prices may consolidate around current levels."

    report_text = (
        f"🕒 **Intraday Gold Report ({datetime.now().strftime('%d %b %Y, %I:%M %p PKT')})**\n\n"
        f"💰 **Current Price:** ${gold_price:.2f}/oz\n"
        f"📊 **Average (simulated):** ${avg_price:.2f}\n"
        f"📈 **Trend:** {'Upward' if recent_trend > 0 else 'Downward' if recent_trend < 0 else 'Flat'}\n\n"
        f"{outlook}"
    )

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report": report_text
    }


# -----------------------------
# DAILY INTRADAY REPORT TO DISCORD
# -----------------------------
def send_daily_report():
    report = generate_intraday_report()
    send_discord_alert(f"🌅 Daily Update (12 AM PKT)\n\n{report['report']}")


# -----------------------------
# PERIODIC ANALYSIS TASK
# -----------------------------
def check_market():
    analysis = analyze_indicators()
    if not analysis:
        return

    signal = analysis["signal"]
    price = analysis["price"]
    confidence = analysis["confidence"]

    if "Buy" in signal or confidence >= 80:
        send_discord_alert(f"💎 **Buy Signal Detected!**\nPrice: ${price}\nConfidence: {confidence}%\nSignal: {signal}")
    elif "Sell" in signal:
        send_discord_alert(f"📉 **Sell Signal Alert!**\nPrice: ${price}\nConfidence: {confidence}%\nSignal: {signal}")


# -----------------------------
# BACKGROUND SCHEDULER
# -----------------------------
def run_scheduler():
    schedule.every(1).hour.do(check_market)       # hourly checks
    schedule.every().day.at("00:00").do(send_daily_report)  # daily report at 12 AM PKT

    while True:
        schedule.run_pending()
        time.sleep(30)


# -----------------------------
# FLASK ENDPOINTS
# -----------------------------
@app.route("/")
def home():
    return jsonify({
        "status": "✅ Gold AI Tracker is live",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/api/intraday")
def intraday_api():
    return jsonify(generate_intraday_report())


# -----------------------------
# RUN EVERYTHING
# -----------------------------
if __name__ == "__main__":
    print("🚀 Gold AI Tracker started")
    threading.Thread(target=run_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=10000, debug=True)
