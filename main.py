import os
import time
import json
import requests
import logging
from datetime import datetime
from transformers import pipeline

# ───────────────────────────────
# CONFIGURATION
# ───────────────────────────────
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON")
HF_TOKEN = os.getenv("HF_TOKEN", "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")
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "goldapi-akhgqzsmgeyofq0-io")

DATA_FILE = "price_history.json"  # stores learning data

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.info("🚀 Starting Gold AI Bot v4 (Self-Learning AI)")

# ───────────────────────────────
# LOAD OR INITIALIZE PRICE HISTORY
# ───────────────────────────────
def load_history():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(DATA_FILE, "w") as f:
        json.dump(history, f, indent=4)

# ───────────────────────────────
# AI MODEL SETUP
# ───────────────────────────────
try:
    ai_analyzer = pipeline(
        "text-generation",
        model="facebook/opt-1.3b",
        use_auth_token=HF_TOKEN
    )
    logging.info("✅ Hugging Face AI model loaded successfully.")
except Exception as e:
    ai_analyzer = None
    logging.warning(f"⚠️ Could not load AI model: {e}")

# ───────────────────────────────
# FETCH GOLD PRICE
# ───────────────────────────────
def fetch_gold_price():
    urls = [
        "https://www.goldapi.io/api/XAU/USD",
        "https://api.exchangerate.host/convert?from=XAU&to=USD"
    ]
    headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if "price" in data:
                return float(data["price"])
            if "result" in data:
                return float(data["result"])

        except Exception as e:
            logging.warning(f"Failed {url}: {e}")

    logging.warning("⚠️ Could not fetch gold price from any source.")
    return None

# ───────────────────────────────
# AI ANALYSIS FUNCTION
# ───────────────────────────────
def ai_analyze(price, history):
    if not ai_analyzer:
        return "AI model unavailable. Check Hugging Face connection."

    # build summary of last few prices
    last_points = [f"${round(p['price'], 2)}" for p in history[-5:]]
    context = ", ".join(last_points) if last_points else "no previous data"

    prompt = (
        f"Previous gold prices were {context}. "
        f"The current price is ${price:.2f}. "
        f"Analyze the trend, predict the next move, and give a short strategy summary."
    )

    try:
        result = ai_analyzer(prompt, max_length=120, num_return_sequences=1)
        return result[0]["generated_text"]
    except Exception as e:
        return f"AI analysis failed: {e}"

# ───────────────────────────────
# DISCORD ALERT FUNCTION
# ───────────────────────────────
def send_discord_message(message):
    if not DISCORD_WEBHOOK:
        logging.warning("⚠️ Discord webhook not configured; skipping send.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message})
        logging.info("✅ Sent message to Discord.")
    except Exception as e:
        logging.warning(f"Failed to send Discord message: {e}")

# ───────────────────────────────
# MAIN BOT LOOP
# ───────────────────────────────
def main():
    history = load_history()

    while True:
        price = fetch_gold_price()
        if price is None:
            logging.error("❌ Could not retrieve gold price.")
        else:
            logging.info(f"💰 Current Gold Price: ${price:.2f}")

            history.append({"time": datetime.now().isoformat(), "price": price})
            if len(history) > 100:
                history = history[-100:]  # keep last 100 records
            save_history(history)

            analysis = ai_analyze(price, history)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            message = (
                f"**Gold Price Update ({timestamp})**\n"
                f"💰 **Current Price:** ${price:.2f}\n"
                f"📈 **Last 5 Prices:** {[round(p['price'],2) for p in history[-5:]]}\n"
                f"🧠 **AI Market Insight:** {analysis}"
            )

            logging.info(message)
            send_discord_message(message)

        logging.info("⏳ Waiting 1 hour for next update...\n")
        time.sleep(3600)  # fetch every hour


if __name__ == "__main__":
    main()
