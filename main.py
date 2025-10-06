from flask import Flask, jsonify
import requests
import threading
import time
import random

app = Flask(__name__)

# =============================
# 🔑 CONFIGURATION
# =============================
GOLDAPI_KEY = "goldapi-favtsmgcmdotp-io"
GOLDAPI_URL = "https://www.goldapi.io/api/XAU/USD"
REFRESH_INTERVAL = 180  # seconds (3 minutes)

# =============================
# 🧾 MEMORY: STORE LAST 10 PRICES
# =============================
gold_price_log = []  # will store tuples: (price, timestamp)

# =============================
# 📊 FETCH GOLD PRICE
# =============================
def fetch_gold_price():
    headers = {
        "x-access-token": GOLDAPI_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(GOLDAPI_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "price" in data:
            price_entry = {
                "price": data["price"],
                "timestamp": data.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
            }

            # Keep log up to last 10 prices
            gold_price_log.append(price_entry)
            if len(gold_price_log) > 10:
                gold_price_log.pop(0)

            print(f"[INFO] 💰 Updated Gold Price: {price_entry['price']}")
            return price_entry
        else:
            print("[WARNING] No price data in API response.")
            return None

    except Exception as e:
        print(f"[ERROR] Failed to fetch gold price: {e}")
        return None

# =============================
# 🔁 AUTO REFRESH THREAD
# =============================
def auto_refresh_prices():
    while True:
        fetch_gold_price()
        time.sleep(REFRESH_INTERVAL)

# Start background thread
threading.Thread(target=auto_refresh_prices, daemon=True).start()

# =============================
# 🧠 MINI NEURAL NET SIMULATION
# =============================
def mini_neural_train():
    if not gold_price_log:
        return "No data to train yet."

    last_prices = [entry["price"] for entry in gold_price_log]
    trend = "uptrend 📈" if last_prices[-1] > sum(last_prices) / len(last_prices) else "downtrend 📉"
    noise_factor = random.uniform(-0.5, 0.5)

    # Simulated "learning"
    learned_value = last_prices[-1] + noise_factor
    return f"Model trained. Detected {trend}, adjusted weight to {learned_value:.2f}"

# =============================
# 🌐 API ROUTES
# =============================
@app.route("/gold", methods=["GET"])
def get_gold():
    if not gold_price_log:
        fetch_gold_price()
    return jsonify({
        "latest_price": gold_price_log[-1] if gold_price_log else "Fetching...",
        "log": gold_price_log
    })

@app.route("/train", methods=["GET"])
def train_ai():
    result = mini_neural_train()
    return jsonify({
        "message": "Training daily with the mini neural net... ✅",
        "result": result
    })

# =============================
# 🚀 MAIN APP
# =============================
if __name__ == "__main__":
    print("[START] 🚀 Gold AI Tracker is running...")
    app.run(debug=True, port=5000)
