import os
import time
import logging
import requests
from discord_webhook import DiscordWebhook, DiscordEmbed
from transformers import pipeline

# ========================
# CONFIGURATION
# ========================
UPDATE_INTERVAL = 300  # 5 minutes

# Load environment variables
HF_TOKEN = os.getenv("HF_TOKEN")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

print("HF_TOKEN detected:", bool(HF_TOKEN))
print("DISCORD_WEBHOOK detected:", bool(DISCORD_WEBHOOK))

if not HF_TOKEN:
    logging.warning("⚠️ HF_TOKEN not set. Please add it as an environment variable.")
else:
    logging.info("✅ Hugging Face token loaded successfully.")

if not DISCORD_WEBHOOK:
    logging.warning("⚠️ DISCORD_WEBHOOK not set. Please add it as an environment variable.")
else:
    logging.info("✅ Discord webhook loaded successfully.")

# ========================
# AI SETUP
# ========================
try:
    ai_model = pipeline(
        "text-classification",
        model="meta-llama/Meta-Llama-3-8B-Instruct",
        token=HF_TOKEN
    )
    logging.info("✅ LLaMA AI model loaded successfully.")
except Exception as e:
    logging.error(f"❌ Failed to load AI model: {e}")
    ai_model = None

# ========================
# MULTI-SOURCE GOLD PRICE FETCHER
# ========================
def fetch_gold_price():
    """Fetch live gold price from multiple reliable APIs with fallback."""
    sources = [
        {
            "name": "Metals.Live",
            "url": "https://api.metals.live/v1/spot/gold",
            "parser": lambda d: float(d[0]["gold"]) if isinstance(d, list) and "gold" in d[0] else None
        },
        {
            "name": "GoldAPI.io",
            "url": "https://www.goldapi.io/api/XAU/USD",
            "headers": {"x-access-token": "goldapi-demo-token"},
            "parser": lambda d: float(d.get("price", 0)) if d.get("price") else None
        },
        {
            "name": "Metals-API",
            "url": "https://api.metals-api.com/v1/latest?access_key=demo&symbols=XAU",
            "parser": lambda d: float(d["rates"]["XAU"]) if "rates" in d and "XAU" in d["rates"] else None
        },
        {
            "name": "Yahoo Finance",
            "url": "https://query1.finance.yahoo.com/v7/finance/quote?symbols=GC=F",
            "parser": lambda d: float(d["quoteResponse"]["result"][0]["regularMarketPrice"])
            if "quoteResponse" in d and d["quoteResponse"]["result"] else None
        },
        {
            "name": "TradingEconomics",
            "url": "https://api.tradingeconomics.com/markets/commodity/gold?c=guest:guest",
            "parser": lambda d: float(d[0]["last"]) if isinstance(d, list) and "last" in d[0] else None
        }
    ]

    for s in sources:
        try:
            logging.info(f"🌐 Trying {s['name']}...")
            r = requests.get(s["url"], headers=s.get("headers", {}), timeout=10)
            if r.status_code != 200:
                logging.warning(f"{s['name']} returned status {r.status_code}")
                continue
            data = r.json()
            price = s["parser"](data)
            if price:
                logging.info(f"✅ {s['name']} success — Price: {price} USD")
                return price
        except Exception as e:
            logging.warning(f"❌ Error fetching from {s['name']}: {e}")

    logging.warning("⚠️ Could not fetch price from any source.")
    return None

# ========================
# AI ANALYSIS
# ========================
def analyze_market(price):
    """Use AI to evaluate whether it's a good buy or sell zone."""
    if not ai_model or not price:
        return "Could not fetch price or load model", 0.0

    text = f"Gold price is {price} USD. Should we buy or sell?"
    result = ai_model(text)[0]
    confidence = round(result['score'] * 100, 2)

    if confidence < 80:
        return f"⚠️ Market uncertain (confidence {confidence}%)", confidence

    label = result['label'].lower()
    if "buy" in label:
        return f"🟢 Buy Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    elif "sell" in label:
        return f"🔴 Sell Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    else:
        return f"⚖️ Hold/Wait — Confidence: {confidence}%\nPrice: {price} USD", confidence

# ========================
# DISCORD ALERT
# ========================
def send_discord_update(title, message, color='ffcc00'):
    """Send update to Discord webhook."""
    if not DISCORD_WEBHOOK:
        logging.warning("Discord webhook not configured; skipping send.")
        return
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK)
        embed = DiscordEmbed(title=title, description=message, color=color)
        embed.set_timestamp()
        webhook.add_embed(embed)
        webhook.execute()
        logging.info(f"📩 Sent update to Discord: {title}")
    except Exception as e:
        logging.error(f"❌ Failed to send Discord message: {e}")

# ========================
# MAIN LOOP
# ========================
def main():
    send_discord_update("🤖 Gold AI Bot Started", "Monitoring live gold markets with AI insights.")
    while True:
        try:
            price = fetch_gold_price()
            if price:
                logging.info(f"💰 Gold Price: {price}")
                analysis, confidence = analyze_market(price)
                if confidence >= 80:
                    send_discord_update("Gold AI Signal", analysis, color='03fc88')
                else:
                    send_discord_update("Gold Market Update", analysis, color='ffcc00')
            else:
                send_discord_update("Gold Price Alert", "⚠️ Could not fetch gold price!", color='ff0000')
        except Exception as e:
            logging.error(f"❌ Error in main loop: {e}")
            send_discord_update("⚠️ Error in Bot", str(e), color='ff0000')

        time.sleep(UPDATE_INTERVAL)

# ========================
# ENTRY POINT
# ========================
if __name__ == "__main__":
    logging.info("🚀 Starting Gold AI Bot Pro v2 (LLaMA, multi-source mode)")
    main()
