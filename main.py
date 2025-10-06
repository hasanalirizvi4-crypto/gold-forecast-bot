import os
import requests
import logging
from flask import Flask, jsonify
from datetime import datetime

# Flask setup
app = Flask(__name__)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ✅ Your GoldAPI.io key
GOLD_API_KEY = "goldapi-favtsmgcmdotp-io"

# ✅ Function to fetch gold price from GoldAPI
def fetch_gold_price():
    url = "https://www.goldapi.io/api/XAU/USD"
    headers = {
        "x-access-token": GOLD_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "price" in data:
            gold_price = data["price"]
            logging.info(f"💰 Updated Gold Price: {gold_price}")
            return gold_price
        else:
            logging.warning("⚠️ GoldAPI response missing 'price' field.")
            return None

    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error fetching gold price: {e}")
        return None


# ✅ API route
@app.route("/gold", methods=["GET"])
def get_gold_price():
    price = fetch_gold_price()
    if price:
        return jsonify({
            "gold_price_usd": price,
            "source": "goldapi.io",
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success"
        })
    else:
        return jsonify({
            "error": "Could not fetch gold price",
            "status": "failed"
        }), 500


# ✅ Root route
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "🏆 Gold Forecast Bot is running!",
        "usage": "Visit /gold to fetch the latest gold price"
    })


# ✅ Render-compatible host binding
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    logging.info("🚀 Gold AI Tracker is running...")
    app.run(host="0.0.0.0", port=port, debug=True)
