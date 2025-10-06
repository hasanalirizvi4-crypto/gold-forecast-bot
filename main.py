import os
import time
import logging
import requests
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

# -------------------------------
# LOAD ENVIRONMENT VARIABLES
# -------------------------------
load_dotenv()

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))

# Hardcoded Gold API key
GOLD_API_KEY = "goldapi-q738vsmgf1dlc3-io"

# -------------------------------
# LOGGING SETUP
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# -------------------------------
# OPENAI CLIENT
# -------------------------------
client = OpenAI(api_key="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")

logging.info("✅ OpenAI client initialized successfully.")

# -------------------------------
# FETCH GOLD PRICE
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
                if src["key"]:
                    keys = src["key"].split(".")
                    for k in keys:
                        data = data.get(k) if isinstance(data, dict) else None
                    if data:
                        return float(data)
                else:
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
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial sentiment analyst. Respond only with Positive, Negative, or Neutral."},
                {"role": "user", "content": news_text}
            ]
        )
        sentiment = response.choices[0].message.content.strip().upper()
        logging.info(f"🧠 AI Sentiment: {sentiment}")
        return sentiment, 1.0
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
# MAIN LOOP
# -------------------------------
def main():
    logging.info("🌟 Gold AI Bot Pro (OpenAI Version) Started 🌟")

    while True:
        price = fetch_gold_price()
        if price:
            sentiment, score = analyze_market_news(f"Gold price is currently {price}. Market reacting with uncertainty.")
            msg = f"💰 Gold Price: **${price:.2f}**\n🧠 Sentiment: **{sentiment}**\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_discord_alert(msg)
            logging.info(msg)
        else:
            logging.warning("⚠️ Could not retrieve gold price.")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
