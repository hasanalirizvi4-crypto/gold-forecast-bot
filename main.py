import os
import requests
import pandas as pd
import numpy as np
import time
import logging
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from datetime import datetime
import joblib

# -----------------------------
# CONFIGURATION
# -----------------------------
HF_TOKEN = os.getenv("HF_TOKEN", "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")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-")

PRICE_LOG = "gold_prices.csv"
MODEL_FILE = "gold_ai_model.pkl"
CHART_FILE = "gold_chart.png"

CHECK_INTERVAL = 1800  # 30 minutes
TRAIN_INTERVAL = 10    # Retrain after 10 prices
SMA_PERIOD = 5         # Simple moving average smoothing

# -----------------------------
# LOGGING SETUP
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# -----------------------------
# FETCH GOLD PRICE
# -----------------------------
def fetch_gold_price():
    urls = [
        "https://api.exchangerate.host/convert?from=XAU&to=USD",
    ]
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if "result" in data and data["result"]:
                return float(data["result"])
        except Exception as e:
            logging.warning(f"Failed {url}: {e}")
    logging.warning("⚠️ Could not fetch gold price from any source.")
    return None


# -----------------------------
# DISCORD MESSAGE HANDLER
# -----------------------------
def send_to_discord(message, image_path=None):
    """Send text and optional image to Discord."""
    if not DISCORD_WEBHOOK:
        logging.warning("Discord webhook not set.")
        return

    data = {"content": message}
    files = {}

    if image_path and os.path.exists(image_path):
        files = {"file": open(image_path, "rb")}

    try:
        requests.post(DISCORD_WEBHOOK, data=data, files=files)
    except Exception as e:
        logging.error(f"Error sending Discord message: {e}")

# -----------------------------
# DATA LOGGING
# -----------------------------
def save_price(price):
    """Save timestamp and price to CSV."""
    df = pd.DataFrame([[datetime.now(), price]], columns=["timestamp", "price"])
    if os.path.exists(PRICE_LOG):
        df.to_csv(PRICE_LOG, mode="a", header=False, index=False)
    else:
        df.to_csv(PRICE_LOG, index=False)

# -----------------------------
# CHARTING
# -----------------------------
def plot_chart():
    """Generate chart with price and moving average."""
    if not os.path.exists(PRICE_LOG):
        return
    df = pd.read_csv(PRICE_LOG)
    df["SMA"] = df["price"].rolling(SMA_PERIOD).mean()

    plt.figure(figsize=(8, 4))
    plt.plot(df["timestamp"], df["price"], label='Gold Price', color='gold', linewidth=2)
    plt.plot(df["timestamp"], df["SMA"], label=f'{SMA_PERIOD}-Period SMA', color='blue', linestyle='--')
    plt.xlabel("Time")
    plt.ylabel("Price (USD)")
    plt.title("Gold Price Trend with SMA")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.legend()
    plt.savefig(CHART_FILE)
    plt.close()

# -----------------------------
# AI MODEL TRAINING
# -----------------------------
def train_and_predict():
    """Train or update model and predict next gold price."""
    if not os.path.exists(PRICE_LOG):
        return None

    df = pd.read_csv(PRICE_LOG)
    if len(df) < SMA_PERIOD + 5:
        return None

    # Smooth prices using moving average
    df["SMA"] = df["price"].rolling(SMA_PERIOD).mean().fillna(method="bfill")

    df["time_idx"] = np.arange(len(df))
    X = df[["time_idx"]]
    y = df["SMA"]

    # Load existing model if available
    if os.path.exists(MODEL_FILE):
        model = joblib.load(MODEL_FILE)
        logging.info("Loaded existing AI model.")
    else:
        model = LinearRegression()

    # Train the model
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)

    next_idx = np.array([[len(df)]])
    predicted = model.predict(next_idx)[0]
    last_price = df["price"].iloc[-1]
    trend = "📈 UP" if predicted > last_price else "📉 DOWN"

    return predicted, trend

# -----------------------------
# MAIN LOOP
# -----------------------------
logging.info("🚀 Starting Gold AI Bot Pro v7 (Smart Market Learning Edition)")
counter = 0

while True:
    price = fetch_gold_price()
    if price:
        save_price(price)
        logging.info(f"💰 Gold Price: ${price}")
        send_to_discord(f"💰 Current Gold Price: ${price}")

        counter += 1
        if counter % TRAIN_INTERVAL == 0:
            result = train_and_predict()
            if result:
                predicted, trend = result
                plot_chart()
                msg = f"🤖 AI Prediction: Next Price ≈ ${predicted:.2f} | Trend: {trend}"
                logging.info(msg)
                send_to_discord(msg, image_path=CHART_FILE)
    else:
        logging.warning("⚠️ Could not fetch gold price from any source.")
        send_to_discord("⚠️ Could not fetch gold price from any source.")

    time.sleep(CHECK_INTERVAL)
