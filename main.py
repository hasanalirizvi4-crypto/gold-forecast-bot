# === main.py ===
"""
Gold AI Bot Pro v2 — API Mode (Hugging Face Inference API)
- Uses multiple price sources for redundancy
- Calls Hugging Face Inference API (Meta-Llama-3-8B-Instruct) for market reasoning
- Sends Discord embeds via webhook
- Persists price history to disk and computes simple EMA + RSI indicators
- Schedules daily summary at 08:00 Pakistan Time (PKT)

USAGE:
1. Create environment variables (recommended) instead of hardcoding:
   - HF_TOKEN           (Hugging Face API token)
   - HF_MODEL           (e.g. meta-llama/Meta-Llama-3-8B-Instruct)
   - DISCORD_WEBHOOK    (Discord webhook URL)
2. pip install -r requirements.txt
3. Deploy to Render or any host. Use a process manager (systemd / container).

NOTE: Do NOT hardcode secrets in source control. Use Render's encrypted environment vars.
"""

import os
import time
import json
import math
import logging
from datetime import datetime, timezone, timedelta
from threading import Thread
import requests
import csv
from statistics import mean

# Third-party: discord_webhook (DiscordWebhook, DiscordEmbed)
from discord_webhook import DiscordWebhook, DiscordEmbed

# Optional numeric helpers
import numpy as np

# ========================
# CONFIG (use env vars)
# ========================
HF_TOKEN = os.getenv("HF_TOKEN")
HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "300"))  # seconds
PRICE_HISTORY_FILE = os.getenv("PRICE_HISTORY_FILE", "price_history.csv")
DAILY_SUMMARY_HOUR_PAKISTAN = int(os.getenv("DAILY_SUMMARY_HOUR_PAKISTAN", "8"))
CONFIDENCE_ALERT_THRESHOLD = float(os.getenv("CONFIDENCE_ALERT_THRESHOLD", "80.0"))

# Basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gold-bot")

# ========================
# PRICE SOURCES
# ========================
PRICE_SOURCES = [
    # public sources (best-effort — some may require API keys in production)
    "https://api.metals.live/v1/spot/gold",
    "https://data-asg.goldprice.org/dbXRates/USD",
    "https://api.metals-api.com/v1/latest?access_key=demo&base=USD&symbols=XAU",
]

# ========================
# HF Inference helper
# ========================
HF_API_BASE = "https://api-inference.huggingface.co/models"


def call_hf_inference(prompt: str, max_tokens: int = 256, timeout: int = 30) -> str:
    """Call the Hugging Face Inference API and return the raw text output.
    Uses the HF_TOKEN and HF_MODEL environment variables.
    """
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN not set in environment")
    url = f"{HF_API_BASE}/{HF_MODEL}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Accept": "application/json"}
    payload = {
        "inputs": prompt,
        "parameters": {"max_new_tokens": max_tokens, "temperature": 0.2},
        "options": {"wait_for_model": True}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    out = resp.json()
    # HF LLM endpoints sometimes return a list of dicts or a dict with 'generated_text'
    if isinstance(out, list) and len(out) > 0 and isinstance(out[0], dict) and 'generated_text' in out[0]:
        return out[0]['generated_text']
    if isinstance(out, dict) and 'generated_text' in out:
        return out['generated_text']
    # otherwise try to extract a string
    if isinstance(out, list) and all(isinstance(x, str) for x in out):
        return "\n".join(out)
    # fallback: stringify whole response
    return json.dumps(out)


# ========================
# Technical indicator helpers
# ========================

def save_price(price: float, ts: datetime = None):
    ts = ts or datetime.utcnow()
    exists = os.path.exists(PRICE_HISTORY_FILE)
    with open(PRICE_HISTORY_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "price"])
        writer.writerow([ts.isoformat(), f"{price:.6f}"])


def load_prices(limit: int = 500) -> list:
    if not os.path.exists(PRICE_HISTORY_FILE):
        return []
    rows = []
    with open(PRICE_HISTORY_FILE, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append(float(r['price']))
            except Exception:
                continue
    return rows[-limit:]


def ema(series: list, period: int = 14) -> float:
    """Calculate the EMA for the last value of the series (period default 14)."""
    if not series or len(series) < period:
        return float(series[-1]) if series else 0.0
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    values = np.array(series[-period:])
    return float(np.convolve(values, weights, mode='valid')[-1])


def rsi(series: list, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    deltas = np.diff(series)
    ups = deltas.clip(min=0)
    downs = -1 * deltas.clip(max=0)
    roll_up = np.mean(ups[-period:])
    roll_down = np.mean(downs[-period:])
    if roll_down == 0:
        return 100.0
    rs = roll_up / roll_down
    return 100.0 - (100.0 / (1.0 + rs))


# ========================
# Price fetching and parsing
# ========================

def fetch_gold_price():
    """Try multiple sources and return the first reliable price (USD per troy ounce)."""
    for url in PRICE_SOURCES:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            # metals.live -> list of {"gold": price}
            if isinstance(data, list) and isinstance(data[0], dict) and 'gold' in data[0]:
                return float(data[0]['gold'])
            # data-asg.goldprice -> {"items": [{"xauPrice" : 1964.12}]}
            if isinstance(data, dict) and 'items' in data and isinstance(data['items'], list) and 'xauPrice' in data['items'][0]:
                return float(data['items'][0]['xauPrice'])
            # metals-api -> {"rates": {"XAU": 0.0005}} (this is base USD case)
            if isinstance(data, dict) and 'rates' in data and 'XAU' in data['rates']:
                return float(data['rates']['XAU'])
        except Exception as e:
            logger.debug(f"fetch error from {url}: {e}")
    return None


# ========================
# Market analysis using HF model (API Mode)
# ========================

def analyze_market_with_llm(price: float, history: list) -> tuple:
    """Ask the LLM to output a decision JSON with fields: decision, confidence, reason.
    decision in {Buy, Sell, Hold}
    confidence: 0-100 (float)
    """
    try:
        # Build a compact prompt that instructs the model to return strict JSON
        prompt = (
            "You are an expert precious-metals quantitative analyst. "
            "Given the latest gold price and recent price history, decide whether to Buy, Sell, or Hold. "
            "Return valid JSON only, with keys: decision (Buy/Sell/Hold), confidence (number 0-100), reason (short string).\n\n"
            f"Current price: {price} USD.\n"
        )
        # Add short price history (last 20 points)
        short_hist = history[-20:]
        if short_hist:
            prompt += "Recent prices (most recent last): " + ", ".join([f"{p:.2f}" for p in short_hist]) + "\n"
        prompt += (
            "Consider technicals (EMA, RSI), macro context, and liquidity. "
            "Be concise. Output only JSON. Example: {\"decision\": \"Buy\", \"confidence\": 86.5, \"reason\": \"Price near support, RSI oversold\"}"
        )

        raw = call_hf_inference(prompt, max_tokens=200)
        # Try to extract JSON from the model output
        text = raw.strip()
        # Sometimes HF returns plain text or extra commentary — try to find the first '{' ... '}'
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_text = text[start:end+1]
            try:
                j = json.loads(json_text)
                decision = j.get('decision', 'Hold')
                confidence = float(j.get('confidence', 0.0))
                reason = j.get('reason', '')
                return decision, confidence, reason
            except Exception:
                pass
        # Fallback: simple keyword parsing
        low = text.lower()
        if 'buy' in low:
            confidence = 85.0
            return 'Buy', confidence, text
        if 'sell' in low:
            confidence = 85.0
            return 'Sell', confidence, text
        return 'Hold', 50.0, text
    except Exception as e:
        logger.exception("LLM analysis failed")
        return 'Hold', 0.0, f'LLM error: {e}'


# ========================
# Discord helpers
# ========================

def send_discord_update(title: str, message: str, color: str = 'ffcc00'):
    if not WEBHOOK_URL:
        logger.warning("Discord webhook not configured; skipping send.")
        return
    try:
        webhook = DiscordWebhook(url=WEBHOOK_URL, rate_limit_retry=True)
        embed = DiscordEmbed(title=title, description=message, color=color)
        embed.set_timestamp()
        webhook.add_embed(embed)
        resp = webhook.execute()
        logger.info(f"Discord message sent (status {getattr(resp, 'status_code', 'n/a')})")
    except Exception as e:
        logger.exception(f"Failed sending Discord message: {e}")


# ========================
# Scheduler: daily summary at 08:00 PKT
# ========================

def is_time_for_daily_summary(now_utc: datetime = None) -> bool:
    # Pakistan time is UTC+5
    now_utc = now_utc or datetime.utcnow().replace(tzinfo=timezone.utc)
    now_pkt = now_utc.astimezone(timezone(timedelta(hours=5)))
    return now_pkt.hour == DAILY_SUMMARY_HOUR_PAKISTAN and now_pkt.minute == 0


# ========================
# Main loop
# ========================

def main_loop():
    last_daily_summary_day = None
    while True:
        try:
            price = fetch_gold_price()
            if price is None:
                logger.warning("Could not fetch price from any source")
                send_discord_update("Gold Price Alert", "⚠️ Could not fetch gold price!", color='ff0000')
                time.sleep(UPDATE_INTERVAL)
                continue

            logger.info(f"Gold price: {price}")
            save_price(price)
            history = load_prices(500)

            decision, confidence, reason = analyze_market_with_llm(price, history)
            title = "Gold AI Signal" if confidence >= CONFIDENCE_ALERT_THRESHOLD else "Gold Market Update"
            color = '03fc88' if decision.lower() == 'buy' else ('ff0000' if decision.lower() == 'sell' else 'ffcc00')
            message = f"Decision: **{decision}**\nConfidence: **{confidence:.2f}%**\nPrice: **{price} USD**\nReason: {reason}"

            # Send immediate alert only if above threshold OR always send summary update
            send_discord_update(title, message, color=color)

            # Daily summary (run once per day at configured hour)
            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            if is_time_for_daily_summary(now):
                day_marker = now.date()
                if day_marker != last_daily_summary_day:
                    last_daily_summary_day = day_marker
                    # build daily summary
                    hist = load_prices(200)
                    if hist:
                        s = f"Latest price: {price} USD\nCount samples: {len(hist)}\nEMA(14): {ema(hist,14):.2f}\nRSI(14): {rsi(hist,14):.2f}"
                    else:
                        s = f"Latest price: {price} USD\nNo historical samples"
                    send_discord_update("Daily Gold Summary (08:00 PKT)", s, color='00aaff')

        except Exception as e:
            logger.exception(f"Main loop error: {e}")
            send_discord_update("⚠️ Error in Bot", str(e), color='ff0000')

        time.sleep(UPDATE_INTERVAL)


if __name__ == '__main__':
    logger.info("Starting Gold AI Bot Pro v2 (API mode)")
    # Sanity checks
    if not HF_TOKEN:
        logger.warning("HF_TOKEN not set. Set environment variable HF_TOKEN to use HF Inference API.")
    if not WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK not set. Set environment variable DISCORD_WEBHOOK to enable Discord alerts.")

    # Start main loop in current process (Render will run this as the web worker / service)
    main_loop()


# If you want to run the model locally instead of API mode (not used by default):
# transformers
# torch
