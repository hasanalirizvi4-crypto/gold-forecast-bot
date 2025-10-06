import os
import time
import logging
import requests
from transformers import pipeline
from datetime import datetime

# -------------------------------
# CONFIG
# -------------------------------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON")
CHECK_INTERVAL = 300  # seconds
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "goldapi-akhgqzsmgeyofq0-io")

# -------------------------------
# LOGGING SETUP
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# -------------------------------
# LOCAL AI SENTIMENT MODEL
# -------------------------------
logging.info("🚀 Loading local AI model (no Hugging Face token required)...")
analyzer = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english")
logging.info("✅ AI model loaded successfully!")

# -------------------------------
# FETCH GOLD PRICE (MULTI-API)
# -------------------------------
def fetch_gold_price():
    sources = [
        {
            "url": "https://www.goldapi.io/api/XAU/USD",
            "headers": {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"},
            "key": "price"
        },
        {
            "url": "https://api.metals.dev/v1/latest",
            "headers": {"accept": "application/json"},
            "key": "metals.gold"
        },
        {
            "url": "https://api.metals.live/v1/spot",
            "headers": {},
            "key": None
        },
    ]
    
    for src in sources:
        try:
            response = requests.get(src["url"], headers=src["headers"], timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Parse based on API format
                if src["key"]:
                    keys = src["key"].split(".")
                    for k in keys:
                        data = data.get(k) if isinstance(data, dict) else None
                    if data:
                        return float(data)
                else:
                    # metals.live returns a list like [{"metal":"gold","price":2345.67},...]
                    if isinstance(data, list) and len(data) > 0 and "gold" in str(data[0]).lower():
                        return float(data[0].get("price", 0))
        except Exception as e:
            logging.warning(f"Failed {src['url']}: {e}")

    logging.warning("⚠️ Could not fetch gold price from any source.")
    return None

# -------------------------------
# AI SENTIMENT ANALYSIS
# -------------------------------
def analyze_market_news(news_text):
    try:
        result = analyzer(news_text[:512])[0]
        sentiment = result["label"]
        score = result["score"]
        logging.info(f"🧠 AI Sentiment: {sentiment} ({score:.2f})")
        return sentiment, score
    except Exception as e:
        logging.error(f"AI Analysis failed: {e}")
        return "NEUTRAL", 0.0

# -------------------------------
# DISCORD ALERT
# -------------------------------
def send_discord_alert(message):
    try:
        data = {"content": message}
        response = requests.post(DISCORD_WEBHOOK, json=data)
        if response.status_code == 204:
            logging.info("✅ Discord alert sent successfully.")
        else:
            logging.warning(f"⚠️ Discord alert failed: {response.text}")
    except Exception as e:
        logging.warning(f"⚠️ Could not send Discord alert: {e}")

# -------------------------------
# MAIN BOT LOOP
# -------------------------------
def main():
    logging.info("🌟 Gold AI Bot Pro (Offline AI Version) Started 🌟")

    while True:
        price = fetch_gold_price()
        if price:
            sentiment, score = analyze_market_news(f"Gold price is currently {price}. Market reacting with uncertainty.")
            
            msg = f"💰 Gold Price: **${price:.2f}**\n🧠 Sentiment: **{sentiment} ({score:.2f})**\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_discord_alert(msg)
            logging.info(msg)
        else:
            logging.warning("⚠️ Could not retrieve gold price.")
        
        time.sleep(CHECK_INTERVAL)

# -------------------------------
# RUN
# -------------------------------
if __name__ == "__main__":
    main()
