import os
import csv
import requests
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestRegressor

# ==============================================
# CONFIGURATION
# ==============================================
HF_TOKEN = "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"
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"

# ==============================================
# FETCH GOLD PRICE (multiple APIs for redundancy)
# ==============================================
def get_gold_price():
    urls = [
        "https://api.metals.live/v1/spot/gold",
        "https://www.goldapi.io/api/XAU/USD",
        "https://api.exchangerate.host/latest?base=XAU&symbols=USD"
    ]
    headers = {"x-access-token": HF_TOKEN}

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                # Handle different API response formats
                if isinstance(data, list):
                    return float(data[0]["gold"])
                elif "price" in data:
                    return float(data["price"])
                elif "rates" in data:
                    return float(1 / data["rates"]["USD"])
        except Exception:
            continue
    print("[WARNING] Could not fetch price from any source")
    return None

# ==============================================
# DISCORD ALERT FUNCTION
# ==============================================
def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        print("[WARNING] Discord webhook not configured; skipping send.")
        return
    try:
        data = {"content": message}
        res = requests.post(DISCORD_WEBHOOK, json=data)
        if res.status_code == 204:
            print("[INFO] Discord alert sent successfully.")
        else:
            print(f"[WARNING] Discord response: {res.status_code}")
    except Exception as e:
        print("[ERROR] Discord send failed:", e)

# ==============================================
# GOLD AI LEARNING SYSTEM
# ==============================================
def log_price(price):
    if not os.path.exists("data"):
        os.makedirs("data")
    filepath = "data/gold_price_history.csv"
    with open(filepath, "a", newline="") as file:
        writer = csv.writer(file)
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
    print("[INFO] Model trained on", len(df), "data points.")
    return model

def predict_next_price(model):
    if model is None:
        return None
    next_index = model.n_features_in_
    prediction = model.predict([[next_index]])[0]
    return prediction

# ==============================================
# MAIN LOOP
# ==============================================
def main():
    print("[INFO] Starting Gold AI Bot Pro v2 (Self-Learning Mode)")
    price = get_gold_price()
    if not price:
        print("[ERROR] Could not retrieve gold price.")
        return

    print(f"[DATA] Current gold price: ${price:.2f}")
    send_discord_alert(f"💰 Current gold price: ${price:.2f}")

    # Log and learn
    log_price(price)
    model = train_model()

    # Predict next price
    if model:
        predicted = predict_next_price(model)
        if predicted:
            print(f"[AI PREDICTION] Next expected price: ${predicted:.2f}")
            send_discord_alert(f"🤖 Gold AI Prediction: Next price ≈ ${predicted:.2f}")
    else:
        print("[INFO] Waiting for more data to train AI model...")

if __name__ == "__main__":
    main()
