#!/usr/bin/env python3
"""
Gold AI Bot — Learning v3
- Fetches gold price hourly (multi-API fallback)
- Logs data to CSV
- Uses a tiny PyTorch MLP to predict next return
- Retrains the MLP once daily in a background thread
- Persists model + scaler so learning survives restarts
- Posts price + prediction + confidence to Discord

ENV required:
  DISCORD_WEBHOOK  - Discord webhook URL
  GOLD_API_KEY     - (optional) GoldAPI key
  UPDATE_INTERVAL  - seconds between price fetches (default 3600)
  DATA_DIR         - directory to store data/models (default "data")
"""

import os
import time
import json
import math
import logging
import threading
from datetime import datetime, timedelta

import requests
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib

import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

# -------------------------
# CONFIG (environment)
# -------------------------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "goldapi-favtsmgcmdotp-io")  # optional
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", str(3600)))  # default hourly
DATA_DIR = os.getenv("DATA_DIR", "data")
HISTORY_CSV = os.path.join(DATA_DIR, "price_history.csv")
MODEL_FILE = os.path.join(DATA_DIR, "nn_model.pt")
SCALER_FILE = os.path.join(DATA_DIR, "scaler.joblib")
LAST_RETRAIN_FILE = os.path.join(DATA_DIR, "last_retrain.json")

# Model / training hyperparams (small)
LAG = int(os.getenv("LAG", "12"))           # number of lagged prices used as features
SMA_PERIOD = int(os.getenv("SMA_PERIOD", "5"))
MIN_SAMPLES_TO_TRAIN = int(os.getenv("MIN_SAMPLES_TO_TRAIN", "200"))
RETRAIN_INTERVAL_SECONDS = int(os.getenv("RETRAIN_INTERVAL_SECONDS", str(24*3600)))  # daily
TRAIN_EPOCHS = int(os.getenv("TRAIN_EPOCHS", "20"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "32"))
LR = float(os.getenv("LEARNING_RATE", "0.001"))
HIDDEN_UNITS = int(os.getenv("HIDDEN_UNITS", "32"))
DEVICE = torch.device("cpu")  # keep CPU-only for Render-compatible

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gold-ai-v3")
logger.info("Starting Gold AI Bot v3 (daily retrain mini-MLP)")

# Ensure data dir
os.makedirs(DATA_DIR, exist_ok=True)

# -------------------------
# Utilities: fetch multi-API gold price
# -------------------------
def fetch_gold_price():
    """Try multiple sources, return USD/oz or None."""
    apis = [
        ("GoldAPI.io", "https://www.goldapi.io/api/XAU/USD", {"x-access-token": GOLD_API_KEY}),
        ("GoldPrice.org", "https://data-asg.goldprice.org/dbXRates/USD", {}),
        ("Metals.live", "https://api.metals.live/v1/spot/gold", {}),
        ("ExchangeRate.host", "https://api.exchangerate.host/convert?from=XAU&to=USD", {}),
        ("YahooFutures", "https://query1.finance.yahoo.com/v7/finance/quote?symbols=GC=F", {}),
    ]
    for name, url, headers in apis:
        try:
            logger.debug("Trying %s", name)
            r = requests.get(url, headers=headers or {}, timeout=8)
            if r.status_code != 200:
                logger.debug("%s returned %s", name, r.status_code)
                continue
            data = r.json()
            # parsers per API
            if name == "GoldAPI.io" and isinstance(data, dict) and data.get("price"):
                return float(data["price"])
            if name == "GoldPrice.org" and isinstance(data, dict):
                itm = data.get("items", [{}])[0]
                if itm.get("xauPrice"):
                    return float(itm["xauPrice"])
            if name == "Metals.live" and isinstance(data, list):
                # metals.live returns list of spot prices, sometimes as dicts containing 'gold'
                first = data[0]
                if isinstance(first, dict) and "gold" in first:
                    # older format returns {"gold": 2345.67}
                    val = first.get("gold")
                    if val:
                        return float(val)
                # some endpoints return {"metal":"gold","price":...}
                if isinstance(first, dict) and "price" in first:
                    return float(first["price"])
            if name == "ExchangeRate.host" and isinstance(data, dict) and "result" in data:
                return float(data["result"])
            if name == "YahooFutures" and isinstance(data, dict):
                q = data.get("quoteResponse", {}).get("result", [{}])[0]
                if q and q.get("regularMarketPrice"):
                    return float(q["regularMarketPrice"])
        except Exception as e:
            logger.debug("API %s failed: %s", name, e)
            continue
    logger.warning("Could not fetch gold price from any source")
    return None

# -------------------------
# Persistence: logging prices
# -------------------------
def append_price(price: float, ts: datetime = None):
    ts = (ts or datetime.utcnow()).isoformat()
    header = not os.path.exists(HISTORY_CSV)
    df = pd.DataFrame([{"timestamp": ts, "price": float(price)}])
    df.to_csv(HISTORY_CSV, mode="a", header=header, index=False)

def load_history_df():
    if not os.path.exists(HISTORY_CSV):
        return pd.DataFrame(columns=["timestamp","price"])
    return pd.read_csv(HISTORY_CSV, parse_dates=["timestamp"])

# -------------------------
# Feature engineering
# -------------------------
def build_features_targets(df: pd.DataFrame, lag=LAG):
    prices = df["price"].values.astype(float)
    n = len(prices)
    if n < lag + 1:
        return None, None
    X_list = []
    y_list = []
    for i in range(lag, n-1):
        window = prices[i-lag:i]  # oldest -> newest
        current = prices[i]
        nextp = prices[i+1]
        # normalized lags relative to last element
        rel = (window / (window[-1] + 1e-12)) - 1.0
        sma = np.mean(window[-SMA_PERIOD:]) if len(window) >= SMA_PERIOD else np.mean(window)
        sma_gap = sma / (current + 1e-12) - 1.0
        vol = np.std(window) / (current + 1e-12)
        feat = np.concatenate([rel, [sma_gap, vol]])
        X_list.append(feat)
        y_list.append((nextp / current) - 1.0)  # predict next return
    X = np.vstack(X_list)
    y = np.array(y_list).reshape(-1,1)
    return X, y

# -------------------------
# Tiny MLP (PyTorch)
# -------------------------
class TinyMLP(nn.Module):
    def __init__(self, input_dim, hidden_units=HIDDEN_UNITS):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_units),
            nn.ReLU(),
            nn.Linear(hidden_units, hidden_units//2 if hidden_units>=4 else 1),
            nn.ReLU(),
            nn.Linear(max(hidden_units//2,1), 1)
        )
    def forward(self, x):
        return self.net(x)

# -------------------------
# Load/save model & scaler
# -------------------------
def save_scaler_and_model(scaler, model):
    joblib.dump(scaler, SCALER_FILE)
    torch.save(model.state_dict(), MODEL_FILE)
    logger.info("Saved model and scaler")

def load_scaler_and_model(input_dim):
    scaler = None
    model = TinyMLP(input_dim).to(DEVICE)
    if os.path.exists(SCALER_FILE):
        scaler = joblib.load(SCALER_FILE)
        logger.info("Loaded scaler")
    if os.path.exists(MODEL_FILE):
        try:
            state = torch.load(MODEL_FILE, map_location=DEVICE)
            model.load_state_dict(state)
            logger.info("Loaded NN model from disk")
        except Exception as e:
            logger.warning("Failed to load NN model: %s", e)
    return scaler, model

# -------------------------
# Training routine (full retrain)
# -------------------------
def train_nn_full(X, y, input_dim):
    logger.info("Starting full NN retrain: samples=%d", X.shape[0])
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    Xt = torch.tensor(Xs, dtype=torch.float32).to(DEVICE)
    yt = torch.tensor(y, dtype=torch.float32).to(DEVICE)

    model = TinyMLP(input_dim).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()

    dataset = TensorDataset(Xt, yt)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    for epoch in range(max(1, TRAIN_EPOCHS)):
        model.train()
        epoch_losses = []
        for xb, yb in loader:
            pred = model(xb)
            loss = loss_fn(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_losses.append(loss.item())
        logger.info("Epoch %d/%d loss %.6f", epoch+1, TRAIN_EPOCHS, float(np.mean(epoch_losses)))
    # Save
    save_scaler_and_model(scaler, model)
    logger.info("Full retrain finished")
    return scaler, model

# -------------------------
# Incremental update (cheap)
# -------------------------
def incremental_update(X, y, scaler, model):
    """Perform a few epochs on latest data (cheap) rather than full retrain."""
    try:
        if scaler is None:
            scaler = StandardScaler()
            scaler.fit(X)
        else:
            # update scaler on X (fit on full X may be better periodically)
            scaler.partial_fit(X) if hasattr(scaler, "partial_fit") else scaler.fit(X)
        Xs = scaler.transform(X)
        Xt = torch.tensor(Xs, dtype=torch.float32).to(DEVICE)
        yt = torch.tensor(y, dtype=torch.float32).to(DEVICE)
        dataset = TensorDataset(Xt, yt)
        loader = DataLoader(dataset, batch_size=max(8, BATCH_SIZE), shuffle=True)
        model.train()
        optimizer = torch.optim.Adam(model.parameters(), lr=LR)
        loss_fn = nn.MSELoss()
        # small number of quick epochs
        for _ in range(3):
            for xb, yb in loader:
                pred = model(xb)
                loss = loss_fn(pred, yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        save_scaler_and_model(scaler, model)
        logger.info("Incremental update done")
        return scaler, model
    except Exception:
        logger.exception("Incremental update failed")
        return scaler, model

# -------------------------
# Predict function wrapper
# -------------------------
def predict_next_return(window_prices, scaler, model):
    if window_prices is None or len(window_prices) < LAG:
        return 0.0, 0.0  # return, confidence
    current = window_prices[-1]
    rel = (window_prices / (window_prices[-1] + 1e-12)) - 1.0
    sma = np.mean(window_prices[-SMA_PERIOD:]) if len(window_prices) >= SMA_PERIOD else np.mean(window_prices)
    sma_gap = sma / (current + 1e-12) - 1.0
    vol = np.std(window_prices) / (current + 1e-12)
    feat = np.concatenate([rel, [sma_gap, vol]]).reshape(1,-1)
    if scaler is None:
        return 0.0, 0.0
    Xs = scaler.transform(feat)
    with torch.no_grad():
        model.eval()
        xt = torch.tensor(Xs, dtype=torch.float32).to(DEVICE)
        pred = model(xt).cpu().numpy()[0][0]
    # confidence estimate: inverse of absolute magnitude of prediction change (simple heuristic)
    conf = max(0.0, 1.0 - min(1.0, abs(pred) * 50.0))  # scaled heuristic
    return float(pred), float(conf)

# -------------------------
# Retrain scheduler (runs in background)
# -------------------------
def run_daily_retrain_lock():
    """Checks last retrain timestamp; if older than RETRAIN_INTERVAL_SECONDS, runs full retrain."""
    # load last retrain time
    last_retrain = None
    if os.path.exists(LAST_RETRAIN_FILE):
        try:
            with open(LAST_RETRAIN_FILE, "r") as f:
                info = json.load(f)
                last_retrain = datetime.fromisoformat(info.get("last_retrain"))
        except Exception:
            last_retrain = None

    now = datetime.utcnow()
    if last_retrain and (now - last_retrain).total_seconds() < RETRAIN_INTERVAL_SECONDS:
        logger.info("No daily retrain needed. Last retrain at %s", last_retrain.isoformat())
        return

    df = load_history_df()
    X, y = build_features_targets(df, lag=LAG)
    if X is None or X.shape[0] < MIN_SAMPLES_TO_TRAIN:
        logger.info("Not enough data to retrain (have %d rows)", df.shape[0])
        return

    input_dim = X.shape[1]
    # train full model
    scaler, model = train_nn_full(X, y, input_dim)
    # store last retrain time
    with open(LAST_RETRAIN_FILE, "w") as f:
        json.dump({"last_retrain": datetime.utcnow().isoformat()}, f)

# -------------------------
# Main loop
# -------------------------
def main_loop():
    # load small metadata & model if exist
    df = load_history_df()
    X, y = build_features_targets(df, lag=LAG)
    scaler = None
    model = None
    if X is not None:
        input_dim = X.shape[1]
        scaler, model = load_scaler_and_model(input_dim)
        # if we have some existing model, run a quick incremental update on current full data
        if model is not None:
            try:
                scaler, model = incremental_update(X, y, scaler, model)
            except Exception:
                pass

    while True:
        try:
            price = fetch_gold_price()
            if price is None:
                logger.warning("No price this cycle")
                time.sleep(UPDATE_INTERVAL)
                continue

            append_price(price, ts=datetime.utcnow())
            logger.info("Fetched price: %.2f", price)

            # reload recent history and predict
            df = load_history_df()
            if len(df) >= LAG:
                window = df["price"].values[-LAG:]
                # ensure model and scaler loaded; if not, attempt to load
                if model is None or scaler is None:
                    Xtmp, ytmp = build_features_targets(df, lag=LAG)
                    if Xtmp is not None:
                        scaler, model = load_scaler_and_model(Xtmp.shape[1])
                if model is not None and scaler is not None:
                    pred_ret, conf = predict_next_return(window, scaler, model)
                    predicted_price = price * (1.0 + pred_ret)
                    msg = f"Price: ${price:.2f} | Pred next: ${predicted_price:.2f} ({pred_ret*100:.3f}%) | Conf: {conf:.2f}"
                else:
                    msg = f"Price: ${price:.2f} | Model warming up..."
                logger.info(msg)
                if DISCORD_WEBHOOK:
                    try:
                        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=8)
                    except Exception:
                        logger.exception("Failed to post to Discord")
            else:
                logger.info("Not enough history yet: %d/%d", len(df), LAG)

            # After each data append, perform a cheap incremental update when possible
            df2 = load_history_df()
            X2, y2 = build_features_targets(df2, lag=LAG)
            if X2 is not None:
                if model is None:
                    scaler, model = train_nn_full(X2, y2, X2.shape[1])
                else:
                    scaler, model = incremental_update(X2, y2, scaler, model)

            # Launch daily retrain in background if due
            t = threading.Thread(target=run_daily_retrain_lock, daemon=True)
            t.start()

        except Exception:
            logger.exception("Main loop error")
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down")
