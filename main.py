# main.py — Multi-source price reconciliation + ATH from spot (XAUUSD=X)
import os
import time
import datetime
import threading
import json
import logging

import requests
import yfinance as yf
import pandas as pd
import numpy as np
import pytz

# -------------------------
# CONFIG (env first, then fallback)
# -------------------------
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL",
    "https://discordapp.com/api/webhooks/1424147581423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON")
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "goldapi-favtsmgcmdotp-io")
METALS_API_KEY = os.getenv("METALS_API_KEY", "a255414b6c7af4586f3b4696bd444950")  # optional backup
TIMEZONE = pytz.timezone("Asia/Karachi")

FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL", 120))  # seconds

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -------------------------
# Discord helper (POST embed JSON to webhook; avoids 405)
# -------------------------
def post_discord_embed(title: str, description: str, color: int = 0xFFD700):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "footer": {"text": "Gold AI Tracker"}
            }
        ]
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code not in (204, 200):
            logging.warning(f"Discord webhook returned {r.status_code}: {r.text}")
    except Exception as e:
        logging.error(f"Discord post failed: {e}")

# -------------------------
# Price sources
# -------------------------
def yahoo_latest(ticker_symbol: str):
    """Return latest close from yfinance ticker (1m data if available)."""
    try:
        t = yf.Ticker(ticker_symbol)
        # use 1d 1m if available, else fallback to 1d 5m or daily
        df = t.history(period="1d", interval="1m")
        if df is None or df.empty:
            df = t.history(period="5d", interval="5m")
            if df is None or df.empty:
                df = t.history(period="365d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logging.debug(f"yahoo_latest({ticker_symbol}) error: {e}")
        return None

def goldapi_latest():
    """Use GoldAPI (fallback)"""
    try:
        headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}
        r = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        if r.status_code == 200:
            j = r.json()
            return float(j.get("price"))
        else:
            logging.debug(f"GoldAPI status {r.status_code}: {r.text}")
            return None
    except Exception as e:
        logging.debug("goldapi_latest error: " + str(e))
        return None

def metals_api_latest():
    """Optional: try a metals API (if key present). Return price or None."""
    if not METALS_API_KEY:
        return None
    try:
        url = f"https://metals-api.com/api/latest?access_key={METALS_API_KEY}&base=USD&symbols=XAU"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            j = r.json()
            # metals-api returns rates["XAU"] as e.g. 0.0005 (XAU per USD). Convert if needed:
            if "rates" in j and "XAU" in j["rates"]:
                rate = float(j["rates"]["XAU"])
                # many metal APIs give XAU as per USD fraction, convert to USD per XAU:
                if rate != 0:
                    return 1.0 / rate
            return None
        else:
            logging.debug(f"metals-api HTTP {r.status_code}")
            return None
    except Exception as e:
        logging.debug("metals_api_latest error: " + str(e))
        return None

# -------------------------
# ATH computation (spot)
# -------------------------
def compute_spot_ath(days=365):
    """Compute ATH (max close) from spot ticker `XAUUSD=X` over `days` days."""
    try:
        t = yf.Ticker("XAUUSD=X")
        df = t.history(period=f"{days}d", interval="1d")
        if df is None or df.empty:
            logging.warning("Could not fetch spot history for ATH calculation.")
            return None
        ath = float(df["Close"].max())
        ath_date = df["Close"].idxmax().strftime("%Y-%m-%d")
        return ath, ath_date
    except Exception as e:
        logging.error(f"compute_spot_ath error: {e}")
        return None

# -------------------------
# Reconciliation logic
# -------------------------
def fetch_all_sources():
    """Fetch prices from multiple sources and return dict."""
    sources = {}
    # primary spot
    sources["yahoo_spot"] = yahoo_latest("XAUUSD=X")
    # futures
    sources["yahoo_futures"] = yahoo_latest("GC=F")
    # goldapi fallback
    sources["goldapi"] = goldapi_latest()
    # metals-api optional
    sources["metals_api"] = metals_api_latest()
    return sources

def pick_preferred_price(sources: dict):
    """Pick preferred price: prefer yahoo_spot if available; else median of valid prices."""
    # collect valid prices
    valid = {k: v for k, v in sources.items() if v is not None and v > 0}
    if not valid:
        return None, None
    # prefer spot
    if "yahoo_spot" in valid:
        return valid["yahoo_spot"], "yahoo_spot"
    # else choose median value
    vals = list(valid.values())
    median = float(pd.Series(vals).median())
    # pick nearest source to median
    nearest_key = min(valid.keys(), key=lambda k: abs(valid[k] - median))
    return median, nearest_key

# -------------------------
# Prev day H/L based on spot
# -------------------------
def get_prev_day_range():
    try:
        t = yf.Ticker("XAUUSD=X")
        df = t.history(period="3d", interval="1d")
        if df is None or df.empty or len(df) < 2:
            return None, None
        prev = df.iloc[-2]
        return float(prev["High"]), float(prev["Low"])
    except Exception as e:
        logging.debug("get_prev_day_range error: " + str(e))
        return None, None

# -------------------------
# Main monitoring loop
# -------------------------
def monitor_loop():
    logging.info("Starting multi-source monitor (spot-pref ATH).")
    # compute initial ATH from spot
    ath_data = compute_spot_ath(days=365)
    if ath_data:
        ATH_value, ATH_date = ath_data
        logging.info(f"Spot ATH (last 365d) = {ATH_value:.2f} on {ATH_date}")
    else:
        ATH_value, ATH_date = None, None

    last_alerted_trend = None
    last_big_move_price = None

    # send initial status with source prices
    sources = fetch_all_sources()
    chosen_price, chosen_source = pick_preferred_price(sources)
    desc = "Initial price sources:\n" + "\n".join([f"- {k}: {v:.2f}" if v else f"- {k}: N/A" for k, v in sources.items()]) \
           + f"\n\nChosen price: {chosen_price:.2f} ({chosen_source})\nSpot ATH: {ATH_value if ATH_value else 'N/A'}"
    post_discord_embed("🤖 GoldBot Live — price sources", desc, color=0x00CC66)

    while True:
        sources = fetch_all_sources()
        price, source_key = pick_preferred_price(sources)

        # Recompute ATH daily at 00:30 PKT
        now = datetime.datetime.now(pytz.timezone("Asia/Karachi"))
        if now.hour == 0 and now.minute == 30:
            ath_data = compute_spot_ath(days=365)
            if ath_data:
                ATH_value, ATH_date = ath_data
                logging.info(f"Recomputed ATH: {ATH_value:.2f} ({ATH_date})")
                post_discord_embed("🔁 ATH updated", f"New spot ATH (365d): {ATH_value:.2f} on {ATH_date}", color=0xFFD700)

        if not price:
            logging.warning("No valid price this cycle; skipping.")
            time.sleep(FETCH_INTERVAL)
            continue

        logging.info(f"Chosen price {price:.2f} from {source_key}")

        # send debug message with source prices in logs once every few cycles (or when mismatched)
        mismatch = False
        valid_prices = [v for v in sources.values() if v]
        if len(valid_prices) >= 2:
            spread = (max(valid_prices) - min(valid_prices)) / min(valid_prices) * 100
            if spread > 0.5:
                mismatch = True

        if mismatch:
            debug_desc = "Source prices differ significantly:\n" + "\n".join(
                [f"- {k}: {v:.2f}" if v else f"- {k}: N/A" for k, v in sources.items()]
            ) + f"\nChosen: {price:.2f} ({source_key})"
            post_discord_embed("⚠️ Source price mismatch", debug_desc, color=0xFF8800)

        # ATH break detection uses spot ATH (if available)
        if ATH_value and price >= ATH_value:
            post_discord_embed("🚀 ATH BREAK", f"Price {price:.2f} ≥ Spot ATH {ATH_value:.2f}.\nSource: {source_key}", color=0x00FF00)
            # update ATH to new level
            ATH_value = price

        # previous day high/low
        prev_high, prev_low = get_prev_day_range()
        if prev_high and price > prev_high:
            post_discord_embed("📈 Prev Day High Broken", f"Price {price:.2f} > Prev High {prev_high:.2f} (source {source_key})")
        if prev_low and price < prev_low:
            post_discord_embed("📉 Prev Day Low Broken", f"Price {price:.2f} < Prev Low {prev_low:.2f} (source {source_key})")

        # big move detection (1% relative to last_big_move_price)
        if last_big_move_price:
            percent_move = (price - last_big_move_price) / last_big_move_price * 100
            if abs(percent_move) >= 1.0:
                title = "🚀 Big Up Move" if percent_move > 0 else "⚠️ Big Drop"
                post_discord_embed(title, f"Price moved {percent_move:.2f}% to {price:.2f} (since {last_big_move_price:.2f})", color=0xFFAA00)
                last_big_move_price = price
        else:
            last_big_move_price = price

        # optionally: compute confidence + indicators (not shown here) or call other functions
        # log to console
        logging.info(f"[CYCLE] price={price:.2f} source={source_key} ATH={ATH_value}")

        time.sleep(FETCH_INTERVAL)

# -------------------------
# Discord wrapper used earlier (keeps previous name)
# -------------------------
def post_discord_embed(title: str, description: str, color: int = 0xFFD700):
    """Wrapper to keep naming consistent with earlier code."""
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "footer": {"text": "Gold AI Tracker"}
            }
        ]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Failed to post discord embed: {e}")

# -------------------------
# Start monitor thread
# -------------------------
if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    # keep main thread alive
    while True:
        time.sleep(60)
