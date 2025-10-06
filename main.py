import sys
import types
import os
import requests
from discord import SyncWebhook, Embed
from datetime import datetime, timedelta
import pytz
import time
from transformers import pipeline

# --- Patch for Python 3.13 (audioop removed) ---
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

# --- CONFIG ---
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
HF_TOKEN = os.getenv("HF_TOKEN", "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")  # your Hugging Face token
TIMEZONE = pytz.timezone("Asia/Karachi")
SEND_HOUR = 8  # Pakistan time for daily report

# === Load Hugging Face model ===
ai = pipeline("text-generation", model="distilbert-base-uncased", device="cpu")

# === Multiple gold price APIs ===
def get_gold_price():
    """Fetch gold price from multiple APIs for accuracy"""
    sources = [
        ("Metals.Live", "https://api.metals.live/v1/spot"),
        ("GoldAPI.io", "https://www.goldapi.io/api/XAU/USD"),
        ("TwelveData", "https://api.twelvedata.com/price?symbol=XAU/USD&apikey=demo"),
        ("BullionVault", "https://data-asg.goldprice.org/dbXRates/USD"),
    ]
    headers = {
        "x-access-token": "goldapi-favtsmgcmdotp-io",
        "Content-Type": "application/json"
    }

    for name, url in sources:
        try:
            resp = requests.get(url, headers=headers if "goldapi" in url else {}, timeout=10)
            data = resp.json()

            # Metals.live
            if name == "Metals.Live" and isinstance(data, list):
                for d in data:
                    if "gold" in d:
                        return float(d["gold"])

            # GoldAPI.io
            elif name == "GoldAPI.io" and "price" in data:
                return float(data["price"])

            # TwelveData
            elif name == "TwelveData" and "price" in data:
                return float(data["price"])

            # BullionVault
            elif name == "BullionVault" and "items" in data:
                return float(data["items"][0]["xauPrice"])
        except Exception as e:
            print(f"{name} failed →", e)
            continue

    return None


# === SENTIMENT SECTION ===
def get_sentiment():
    """Generate gold sentiment using Hugging Face AI"""
    try:
        prompt = (
            "Analyze gold market sentiment for today considering USD strength, inflation, "
            "interest rates, and geopolitical factors. Give short result as Bullish, Bearish, or Neutral "
            "with confidence level."
        )

        ai_result = ai(prompt, max_length=120, num_return_sequences=1)
        analysis = ai_result[0]["generated_text"]

        if "bullish" in analysis.lower():
            overall = "Bullish"
        elif "bearish" in analysis.lower():
            overall = "Bearish"
        else:
            overall = "Neutral"

        return {
            "Overall Sentiment": overall,
            "Confidence": "High" if "80" in analysis or "strong" in analysis else "Moderate",
            "AI Insight": analysis.strip(),
        }

    except Exception as e:
        print("AI sentiment error:", e)
        return {"Overall Sentiment": "Neutral", "Confidence": "Low", "AI Insight": "Fallback mode used"}


# === ZONE DETECTOR ===
def get_zones(price):
    """Calculate strong buy/sell zones dynamically based on price"""
    if not price:
        return None, None

    buy_zone_low = round(price * 0.995, 2)
    buy_zone_high = round(price * 0.997, 2)
    sell_zone_low = round(price * 1.003, 2)
    sell_zone_high = round(price * 1.005, 2)

    return (buy_zone_low, buy_zone_high), (sell_zone_low, sell_zone_high)


# === PROBABILITY CHECK ===
def check_probability(sentiment):
    """Estimate trade confidence"""
    conf_map = {"High": 90, "Moderate": 75, "Low": 50}
    return conf_map.get(sentiment.get("Confidence", "Low"), 50)


# === DISCORD UPDATE ===
def send_discord_update():
    webhook = SyncWebhook.from_url(WEBHOOK_URL)
    embed = Embed(
        title="🏆 Gold AI Forecast",
        description="Comprehensive daily and intraday analysis powered by AI 🤖",
        color=0xFFD700,
        timestamp=datetime.now(TIMEZONE)
    )

    gold_price = get_gold_price()
    sentiment = get_sentiment()

    # --- PRICE ---
    if gold_price:
        embed.add_field(name="🏅 Current Gold Price (USD/oz)", value=f"${gold_price:,}", inline=False)
    else:
        embed.add_field(name="🏅 Current Gold Price (USD/oz)", value="⚠️ Could not fetch gold price", inline=False)

    # --- ZONES ---
    buy_zone, sell_zone = get_zones(gold_price)
    if buy_zone and sell_zone:
        embed.add_field(name="💰 Buy Zone", value=f"{buy_zone[0]} – {buy_zone[1]}", inline=True)
        embed.add_field(name="📈 Sell Zone", value=f"{sell_zone[0]} – {sell_zone[1]}", inline=True)
    else:
        embed.add_field(name="💰 Zones", value="Unavailable", inline=False)

    # --- SENTIMENT ---
    sentiment_text = "\n".join([f"**{k}:** {v}" for k, v in sentiment.items()])
    embed.add_field(name="🧠 Market Sentiment", value=sentiment_text, inline=False)

    # --- ALERT ---
    confidence = check_probability(sentiment)
    if confidence >= 80:
        embed.add_field(
            name="🚨 Trade Alert",
            value="High-confidence trade setup detected! Monitor gold closely 🔥",
            inline=False
        )

    embed.set_footer(text="Gold AI Bot • by Hasan Ali • Powered by Hugging Face")

    webhook.send(embed=embed)
    print(f"✅ Update sent at {datetime.now(TIMEZONE)} | Confidence: {confidence}%")


# === SCHEDULER ===
def run_scheduler():
    print("🚀 Gold AI Bot running — awaiting 8 AM Pakistan Time...")
    while True:
        now = datetime.now(TIMEZONE)
        target = now.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)

        if target <= now < target + timedelta(minutes=1):
            send_discord_update()
            time.sleep(60)
        time.sleep(30)


# === MAIN ===
if __name__ == "__main__":
    send_discord_update()  # send immediately when started
    run_scheduler()
