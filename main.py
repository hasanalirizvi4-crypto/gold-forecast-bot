import os
import requests
import time
from discord_webhook import DiscordWebhook, DiscordEmbed
from transformers import pipeline

# ========================
# CONFIG
# ========================
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
HF_TOKEN = "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"
UPDATE_INTERVAL = 300  # seconds (5 min)

# ========================
# AI SETUP
# ========================
ai_model = pipeline("text-classification", model="facebook/bart-large-mnli", token=HF_TOKEN)

# ========================
# FUNCTIONS
# ========================
def fetch_gold_price():
    """Fetch gold prices from multiple sources for reliability."""
    urls = [
        "https://api.metals.live/v1/spot/gold",
        "https://data-asg.goldprice.org/dbXRates/USD",
        "https://api.metals-api.com/v1/latest?access_key=demo&base=USD&symbols=XAU"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            # Parse depending on structure
            if isinstance(data, list) and "gold" in data[0]:
                return float(data[0]["gold"])
            elif "items" in data and "xauPrice" in data["items"][0]:
                return float(data["items"][0]["xauPrice"])
            elif "rates" in data and "XAU" in data["rates"]:
                return float(data["rates"]["XAU"])
        except Exception as e:
            print(f"❌ Error fetching from {url}: {e}")
    return None


def analyze_market(price):
    """Use AI to evaluate whether it's a good buy or sell zone."""
    if not price:
        return "Could not fetch price", 0.0

    # Simple technical + sentiment logic
    text = f"Gold price is {price} USD. Should we buy or sell?"
    result = ai_model(text)[0]
    confidence = round(result['score'] * 100, 2)
    
    if confidence < 80:
        return f"⚠️ Market uncertain (confidence {confidence}%)", confidence

    if "buy" in result['label'].lower():
        return f"🟢 Buy Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    elif "sell" in result['label'].lower():
        return f"🔴 Sell Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    else:
        return f"⚖️ Hold/Wait — Confidence: {confidence}%", confidence


def send_discord_update(title, message, color='ffcc00'):
    """Send update to Discord webhook."""
    webhook = DiscordWebhook(url=WEBHOOK_URL)
    embed = DiscordEmbed(title=title, description=message, color=color)
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()


def main():
    last_price = None
    while True:
        try:
            price = fetch_gold_price()
            if price:
                print(f"💰 Gold Price: {price}")
                analysis, confidence = analyze_market(price)

                # Only alert on > 80% confidence
                if confidence >= 80:
                    send_discord_update("Gold AI Signal", analysis, color='03fc88')
                else:
                    send_discord_update("Gold Market Update", f"Price: {price}\n{analysis}", color='ffcc00')
            else:
                send_discord_update("Gold Price Alert", "⚠️ Could not fetch gold price!", color='ff0000')

        except Exception as e:
            send_discord_update("⚠️ Error in Bot", str(e), color='ff0000')

        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    send_discord_update("🤖 Gold AI Bot Started", "Monitoring live gold markets with AI insights.")
    main()
