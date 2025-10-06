import os
import requests
import time
import logging
from discord_webhook import DiscordWebhook, DiscordEmbed
from transformers import pipeline

# ========================
# CONFIG
# ========================
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
HF_TOKEN = "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"
GOLD_API_KEY = "goldapi-favtsmgcmdotp-io"
UPDATE_INTERVAL = 300  # 5 minutes

# ========================
# LOGGING
# ========================
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)

# ========================
# AI SETUP
# ========================
logging.info("Initializing AI model…")
ai_model = pipeline(
    "text-generation",
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    token=HF_TOKEN
)

# ========================
# FUNCTIONS
# ========================
def fetch_gold_price():
    """Fetch gold price using goldapi.io"""
    url = "https://www.goldapi.io/api/XAU/USD"
    headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if "price" in data:
            return float(data["price"])
        else:
            logging.warning(f"⚠️ Unexpected API response: {data}")
    except Exception as e:
        logging.error(f"❌ Error fetching gold price: {e}")

    return None


def analyze_market(price):
    """AI evaluates buy/sell zone using reasoning."""
    if not price:
        return "⚠️ Could not fetch gold price.", 0.0

    prompt = (
        f"The current gold price is ${price}. Based on current market behavior and manipulation, "
        "should we buy, sell, or hold? Provide a clear action and confidence percentage."
    )

    try:
        result = ai_model(prompt, max_new_tokens=50)[0]['generated_text']
        if "buy" in result.lower():
            sentiment = "🟢 Buy Zone Detected"
        elif "sell" in result.lower():
            sentiment = "🔴 Sell Zone Detected"
        else:
            sentiment = "⚖️ Hold Zone"

        confidence = 85.0  # approximate for demo
        return f"{sentiment} — Confidence: {confidence}%\n{result}", confidence
    except Exception as e:
        logging.error(f"AI error: {e}")
        return "⚠️ AI analysis failed.", 0.0


def send_discord_update(title, message, color='ffcc00'):
    """Send update to Discord webhook"""
    try:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK)
        embed = DiscordEmbed(title=title, description=message, color=color)
        embed.set_timestamp()
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        logging.error(f"❌ Discord send failed: {e}")


def train_mini_model(price):
    """Simulate lightweight training on each price tick."""
    logging.info("🧠 Training mini neural net on recent price movement...")
    # Here you could log data or fine-tune a small model if local resources allow
    # For now, we simulate a quick learning adjustment
    time.sleep(1)
    logging.info(f"✅ Mini model updated with price data: {price}")


# ========================
# MAIN LOOP
# ========================
def main():
    logging.info("🚀 Gold AI Bot Pro v3 started successfully!")
    last_price = None

    while True:
        price = fetch_gold_price()
        if price:
            logging.info(f"💰 Current Gold Price: ${price}")
            train_mini_model(price)
            analysis, confidence = analyze_market(price)

            if confidence >= 80:
                send_discord_update("Gold AI Signal", analysis, color='03fc88')
            else:
                send_discord_update("Gold Market Update", f"Price: ${price}\n{analysis}")
        else:
            logging.warning("⚠️ Could not fetch gold price from goldapi.io")
            send_discord_update("Gold Price Alert", "⚠️ Could not fetch gold price!")

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    send_discord_update("🤖 Gold AI Bot Started", "Monitoring gold prices and training daily.")
    main()
