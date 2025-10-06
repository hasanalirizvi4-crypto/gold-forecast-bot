import os
import time
import csv
import random
import requests
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestRegressor
from transformers import pipeline
from discord_webhook import DiscordWebhook, DiscordEmbed

# ==============================
# CONFIG
# ==============================
HF_TOKEN = os.getenv("HF_TOKEN", "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")
WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK",
    "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
)
UPDATE_INTERVAL = 300  # seconds (5 min)

# ==============================
# AI MODEL (Inference API mode)
# ==============================
print("[INFO] Starting Gold AI Bot Pro v2 (API mode)")
ai_model = pipeline(
    "text-classification",
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    token=HF_TOKEN
)

# ==============================
# DISCORD ALERT FUNCTION
# ==============================
def send_discord_update(title, message, color="ffcc00"):
    try:
        webhook = DiscordWebhook(url=WEBHOOK_URL)
        embed = DiscordEmbed(title=title, description=message, color=color)
        embed.set_timestamp()
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        print(f"[WARNING] Discord send failed: {e}")

# ==============================
# MULTI-API GOLD PRICE FETCHER
# ==============================
def fetch_gold_price():
    """Fetch current gold price (USD/oz) from multiple APIs with fallback."""
    urls = [
        "https://api.metals.live/v1/spot/gold",
        "https://api.goldapi.io/api/XAU/USD",
        "https://data-asg.goldprice.org/dbXRates/USD",
        "https://api.exchangerate.host/latest?base=XAU&symbols=USD"
    ]
    headers = {
        "x-access-token": "goldapi-demo-key-12345",  # Replace with real key if you have one
        "User-Agent": "Mozilla/5.0"
    }

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()

            if isinstance(data, list) and "gold" in data[0]:
                return float(data[0]["gold"])
            elif "price" in data:
                return float(data["price"])
            elif "items" in data and "xauPrice" in data["items"][0]:
                return float(data["items"][0]["xauPrice"])
            elif "rates" in data and "USD" in data["rates"]:
                usd_per_ounce = 1 / float(data["rates"]["USD"])
                return round(usd_per_ounce, 2)

        except Exception as e:
            print(f"[WARNING] Could not fetch price from {url}: {e}")
            time.sleep(random.uniform(1, 3))
            continue

    print("[ERROR] Could not retrieve gold price from any API.")
    return None

# ==============================
# AI MARKET ANALYSIS
# ==============================
def analyze_market(price):
    if not price:
        return "Could not fetch price", 0.0

    text = f"Gold price is {price} USD. Should we buy or sell?"
    result = ai_model(text)[0]
    confidence = round(result["score"] * 100, 2)

    if confidence < 80:
        return f"⚠️ Market uncertain (confidence {confidence}%)", confidence

    label = result["label"].lower()
    if "buy" in label:
        return f"🟢 Buy Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    elif "sell" in label:
        return f"🔴 Sell Zone Detected — Confidence: {confidence}%\nPrice: {price} USD", confidence
    else:
        return f"⚖️ Hold/Wait — Confidence: {confidence}%", confidence

# ==============================
# SELF-LEARNING SYSTEM
# ==============================
def log_price(price):
    os.makedirs("data", exist_ok=True)
    filepath = "data/gold_price_history.csv"
    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), price])

def train_model():
    filepath = "data/gold_price_history.csv"
    if not os.path.exists(filepath):
        print("[INFO] No training data yet.")
        return None

    df = pd.read_csv(filepath, header=None, names=["timestamp", "price"])
    if len(df) < 20:
        print("[INFO] Not enough data to train yet.")
        return None

    df["time_index"] = range(len(df))
    X = df[["time_index"]]
    y = df["price"]

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)
    print(f"[INFO] Model trained on {len(df)} points.")
    return model

def predict_next_price(model):
    if model is None:
        return None
    next_index = model.n_features_in_
    return model.predict([[next_index]])[0]

# ==============================
# MAIN LOOP
# ==============================
def main():
    send_discord_update("🤖 Gold AI Bot Started", "Monitoring live gold markets with AI insights.")
    while True:
        try:
            price = fetch_gold_price()
            if not price:
                send_discord_update("⚠️ Gold Price Alert", "Could not fetch gold price!", color="ff0000")
                time.sleep(UPDATE_INTERVAL)
                continue

            print(f"[PRICE] 💰 Gold Price: {price} USD")
            log_price(price)

            # Train and predict future trend
            model = train_model()
            if model:
                prediction = predict_next_price(model)
                if prediction:
                    print(f"[AI PREDICTION] Next expected price ≈ {prediction:.2f} USD")
                    send_discord_update("📈 AI Predicted Next Price", f"≈ ${prediction:.2f}")

            # AI analysis
            analysis, confidence = analyze_market(price)
            print(f"[ANALYSIS] {analysis}")

            if confidence >= 80:
                send_discord_update("Gold AI Signal", analysis, color="03fc88")
            else:
                send_discord_update("Gold Market Update", f"Price: {price}\n{analysis}", color="ffcc00")

        except Exception as e:
            send_discord_update("⚠️ Bot Error", str(e), color="ff0000")

        time.sleep(UPDATE_INTERVAL)

# ==============================
if __name__ == "__main__":
    main()
