"""
Gold AI Bot — Self-Learning Edition
- Multi-API gold price fetcher (fallbacks)
- Local sentiment analysis (optional)
- Persistent incremental learning:
    - SGDRegressor for online updates (fast)
    - Periodic RandomForest retrain for stronger model
- Saves price history to CSV and models with joblib
- Sends Discord alerts via webhook
"""

import os
import time
import math
import logging
import requests
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.linear_model import SGDRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error

# OPTIONAL: local transformer for sentiment (no HF token required)
try:
    from transformers import pipeline
    HAS_TRANSFORMERS = True
except Exception:
    HAS_TRANSFORMERS = False

# -------------------------
# CONFIG (use env vars)
# -------------------------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")  # set in Render
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "")   # optional, e.g. goldapi-...
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "300"))  # seconds between fetches
DATA_DIR = os.getenv("DATA_DIR", "data")
HISTORY_CSV = os.path.join(DATA_DIR, "price_history.csv")
SGD_MODEL_FILE = os.path.join(DATA_DIR, "sgd_model.joblib")
RF_MODEL_FILE = os.path.join(DATA_DIR, "rf_model.joblib")
SCALER_FILE = os.path.join(DATA_DIR, "scaler.joblib")

# Training params
LAG = int(os.getenv("LAG", "10"))  # number of lagged prices used as features
MIN_TRAIN_SAMPLES = int(os.getenv("MIN_TRAIN_SAMPLES", "200"))
RF_RETRAIN_BATCH = int(os.getenv("RF_RETRAIN_BATCH", "500"))  # perform RF retrain after this many new samples
SMA_PERIOD = int(os.getenv("SMA_PERIOD", "5"))

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gold-learning-bot")

logger.info("Starting Gold AI Bot — self-learning edition")
logger.info("DISCORD_WEBHOOK present: %s", bool(DISCORD_WEBHOOK))
logger.info("TRANSFORMERS available: %s", HAS_TRANSFORMERS)

# -------------------------
# Ensure data dir
# -------------------------
os.makedirs(DATA_DIR, exist_ok=True)

# -------------------------
# Load / init sentiment model
# -------------------------
sentiment_pipeline = None
if HAS_TRANSFORMERS:
    try:
        # lightweight local sentiment model
        sentiment_pipeline = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english")
        logger.info("Loaded local sentiment pipeline")
    except Exception as e:
        logger.warning("Failed to load local transformer model: %s", e)
        sentiment_pipeline = None

# -------------------------
# Multi-source price fetcher
# -------------------------
def fetch_gold_price():
    # prioritized list of sources (name, url, headers, parser)
    apis = [
        ("GoldAPI.io", "https://www.goldapi.io/api/XAU/USD",
         {"x-access-token": GOLD_API_KEY} if GOLD_API_KEY else {}, lambda d: d.get("price") if isinstance(d, dict) else None),
        ("GoldPrice.org", "https://data-asg.goldprice.org/dbXRates/USD", {}, lambda d: d.get("items", [{}])[0].get("xauPrice") if isinstance(d, dict) else None),
        ("Metals.live", "https://api.metals.live/v1/spot/gold", {}, lambda d: float(d[0]["gold"]) if isinstance(d, list) and "gold" in d[0] else None),
        ("ExchangeRate.host", "https://api.exchangerate.host/convert?from=XAU&to=USD", {}, lambda d: d.get("result") if isinstance(d, dict) else None),
        ("YahooFutures", "https://query1.finance.yahoo.com/v7/finance/quote?symbols=GC=F", {}, lambda d: d.get("quoteResponse", {}).get("result", [{}])[0].get("regularMarketPrice") if isinstance(d, dict) else None),
        ("Metals-API-demo", "https://metals-api.com/api/latest?access_key=demo&base=USD&symbols=XAU", {}, lambda d: d.get("rates", {}).get("XAU") if isinstance(d, dict) else None),
    ]

    for name, url, headers, parser in apis:
        try:
            logger.info("Trying %s", name)
            r = requests.get(url, headers=headers or {}, timeout=8)
            if r.status_code != 200:
                logger.debug("%s returned status %s", name, r.status_code)
                continue
            data = r.json()
            price = parser(data)
            if price is None:
                logger.debug("%s returned unexpected payload", name)
                continue
            price = float(price)
            if price <= 0 or math.isnan(price):
                logger.debug("%s returned invalid price: %s", name, price)
                continue
            logger.info("Fetched price from %s: %s", name, price)
            return price
        except Exception as e:
            logger.warning("Error fetching from %s: %s", name, e)
            continue

    logger.warning("Could not fetch price from any source")
    return None

# -------------------------
# Persistence: CSV functions
# -------------------------
def append_price(price: float, timestamp: datetime = None, sentiment_label: str = None, sentiment_score: float = None, predicted: float = None):
    ts = (timestamp or datetime.utcnow()).isoformat()
    header = not os.path.exists(HISTORY_CSV)
    row = {"timestamp": ts, "price": float(price), "sentiment": sentiment_label, "sentiment_score": sentiment_score, "predicted": predicted}
    df = pd.DataFrame([row])
    df.to_csv(HISTORY_CSV, mode="a", header=header, index=False)

def load_history():
    if not os.path.exists(HISTORY_CSV):
        return pd.DataFrame(columns=["timestamp","price","sentiment","sentiment_score","predicted"])
    df = pd.read_csv(HISTORY_CSV, parse_dates=["timestamp"])
    return df

# -------------------------
# Feature engineering
# -------------------------
def build_features(df: pd.DataFrame, lag: int = LAG):
    """
    Build features for supervised learning:
    - lagged normalized prices (lag values normalized to most recent in window)
    - SMA gap
    - volatility (std) of window
    Target: next return ((p_{t+1} / p_t) - 1)
    """
    series = df["price"].values
    n = len(series)
    X_rows = []
    y = []
    if n < lag + 1:
        return None, None
    for i in range(lag, n-1):
        window = series[i-lag:i]
        current = series[i]
        nextp = series[i+1]
        rel_lags = (window / window[-1]) - 1.0  # relative lags
        sma = np.mean(window[-SMA_PERIOD:]) if len(window) >= SMA_PERIOD else np.mean(window)
        sma_gap = sma / current - 1.0
        vol = np.std(window) / (current + 1e-9)
        feats = np.concatenate([rel_lags, [sma_gap, vol]])
        X_rows.append(feats)
        y.append((nextp / current) - 1.0)
    X = np.vstack(X_rows)
    y = np.array(y)
    return X, y

# -------------------------
# Model management
# -------------------------
sgd_model = None
scaler = None
rf_model = None
samples_since_rf = 0

def load_models():
    global sgd_model, scaler, rf_model
    if os.path.exists(SGD_MODEL_FILE):
        try:
            sgd_model = joblib.load(SGD_MODEL_FILE)
            logger.info("Loaded SGD model")
        except Exception:
            logger.exception("Failed to load SGD model")
    if os.path.exists(SCALER_FILE):
        try:
            scaler = joblib.load(SCALER_FILE)
            logger.info("Loaded scaler")
        except Exception:
            logger.exception("Failed to load scaler")
    if os.path.exists(RF_MODEL_FILE):
        try:
            rf_model = joblib.load(RF_MODEL_FILE)
            logger.info("Loaded RF model")
        except Exception:
            logger.exception("Failed to load RF model")

def save_models():
    try:
        if sgd_model is not None:
            joblib.dump(sgd_model, SGD_MODEL_FILE)
        if scaler is not None:
            joblib.dump(scaler, SCALER_FILE)
        if rf_model is not None:
            joblib.dump(rf_model, RF_MODEL_FILE)
    except Exception:
        logger.exception("Failed to save models")

def initialize_models(feature_dim):
    global sgd_model, scaler
    if scaler is None:
        scaler = StandardScaler()
    if sgd_model is None:
        sgd_model = SGDRegressor(max_iter=1000, tol=1e-3)

# -------------------------
# Training and updating
# -------------------------
def train_full():
    """Full retrain (RandomForest) on whole dataset for stronger model."""
    global rf_model, samples_since_rf, scaler
    df = load_history()
    if df.shape[0] < MIN_TRAIN_SAMPLES:
        logger.info("Not enough data for full retrain: %d/%d", df.shape[0], MIN_TRAIN_SAMPLES)
        return
    X, y = build_features(df, lag=LAG)
    if X is None:
        logger.info("Not enough rows after feature build")
        return
    initialize_models(X.shape[1])
    scaler.fit(X)
    Xs = scaler.transform(X)
    try:
        logger.info("Training RandomForest (this may take a bit)...")
        rf = RandomForestRegressor(n_estimators=150, n_jobs=1, random_state=42)
        rf.fit(Xs, y)
        rf_model = rf
        samples_since_rf = 0
        joblib.dump(rf_model, RF_MODEL_FILE)
        joblib.dump(scaler, SCALER_FILE)
        logger.info("RandomForest retrain done and saved.")
    except Exception:
        logger.exception("RandomForest training failed")

def online_update():
    """Quick online update using SGD partial_fit on the most recent batch."""
    global sgd_model, scaler, samples_since_rf
    df = load_history()
    X, y = build_features(df, lag=LAG)
    if X is None:
        return
    initialize_models(X.shape[1])
    # Fit scaler on X (small online re-fit is acceptable)
    try:
        scaler.partial_fit(X)
    except Exception:
        scaler.fit(X)
    Xs = scaler.transform(X)
    # If sgd_model not yet initialized with coefficients, do initial partial_fit
    try:
        if getattr(sgd_model, "coef_", None) is None:
            sgd_model.partial_fit(Xs, y)
        else:
            sgd_model.partial_fit(Xs, y)
        samples_since_rf += len(y)
        joblib.dump(sgd_model, SGD_MODEL_FILE)
        joblib.dump(scaler, SCALER_FILE)
        logger.info("SGD online update done. Samples pending RF retrain: %d", samples_since_rf)
    except Exception:
        logger.exception("SGD partial_fit failed")

# -------------------------
# Prediction
# -------------------------
def predict_next(window_prices):
    """
    Input: window_prices = numpy array of last LAG prices (oldest->newest)
    Returns predicted_return, method (rf/sgd/none)
    """
    global sgd_model, rf_model, scaler
    if window_prices is None or len(window_prices) < LAG:
        return 0.0, "none"
    current = window_prices[-1]
    rel_lags = (window_prices / window_prices[-1]) - 1.0
    sma = np.mean(window_prices[-SMA_PERIOD:]) if len(window_prices) >= SMA_PERIOD else np.mean(window_prices)
    sma_gap = sma / current - 1.0
    vol = np.std(window_prices) / (current + 1e-9)
    feat = np.concatenate([rel_lags, [sma_gap, vol]]).reshape(1, -1)
    if scaler is None:
        return 0.0, "none"
    Xs = scaler.transform(feat)
    # prefer rf if available
    try:
        if rf_model is not None:
            p = rf_model.predict(Xs)[0]
            return float(p), "rf"
    except Exception:
        logger.debug("RF predict failed")
    try:
        if sgd_model is not None:
            p = sgd_model.predict(Xs)[0]
            return float(p), "sgd"
    except Exception:
        logger.debug("SGD predict failed")
    return 0.0, "none"

# -------------------------
# Sentiment helper
# -------------------------
def analyze_sentiment(text: str):
    if sentiment_pipeline is None:
        return None, None
    try:
        out = sentiment_pipeline(text[:512])[0]
        return out.get("label"), float(out.get("score"))
    except Exception:
        logger.exception("Sentiment analysis failed")
        return None, None

# -------------------------
# Discord helper
# -------------------------
def send_discord(text: str):
    if not DISCORD_WEBHOOK:
        logger.warning("Discord webhook not configured; skipping send.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=10)
    except Exception:
        logger.exception("Failed to send Discord message")

# -------------------------
# Main loop
# -------------------------
def main_loop():
    global samples_since_rf
    load_models()
    # initial online update if model files exist
    online_update()

    while True:
        try:
            price = fetch_gold_price()
            if price is None:
                logger.warning("No price fetched this cycle")
                send_discord("⚠️ Could not fetch gold price this cycle.")
                time.sleep(UPDATE_INTERVAL)
                continue

            # sentiment (optional)
            sentiment_label, sentiment_score = analyze_sentiment(f"Gold price {price}") if sentiment_pipeline else (None, None)

            # append to CSV
            append_price(price, timestamp=datetime.utcnow(), sentiment_label=sentiment_label, sentiment_score=sentiment_score, predicted=None)

            # load history and predict
            df = load_history()
            logger.info("History length: %d", len(df))
            if len(df) >= LAG:
                window = df["price"].values[-LAG:]
                pred_ret, method = predict_next(window)
                predicted_price = price * (1.0 + pred_ret)
                msg = (f"Gold: ${price:.2f} | Predicted next: ${predicted_price:.2f} ({pred_ret*100:.3f}% via {method})\n"
                       f"Sentiment: {sentiment_label} {('%.2f'%sentiment_score) if sentiment_score else ''}\n"
                       f"Samples: {len(df)}")
                logger.info(msg)
                send_discord(msg)
                # update last row's predicted field
                df = load_history()
                if not df.empty:
                    df.at[df.index[-1], "predicted"] = predicted_price
                    df.to_csv(HISTORY_CSV, index=False)

            # online update with new data
            online_update()

            # if enough new samples, retrain RandomForest
            if samples_since_rf >= RF_RETRAIN_BATCH:
                train_full()  # does reset samples_since_rf
                # after RF retrain, reload models (rf_model set inside train_full)
                load_models()

        except Exception:
            logger.exception("Main loop error")
            send_discord("⚠️ Bot error occurred; check logs.")

        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down; saving models")
        save_models()
    except Exception:
        logger.exception("Fatal error; saving models")
        save_models()
