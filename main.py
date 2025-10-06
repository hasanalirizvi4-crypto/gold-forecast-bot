# main.py
import sys, types
# patch for Python 3.13 missing audioop
if 'audioop' not in sys.modules:
    import types as _types
    sys.modules['audioop'] = _types.ModuleType('audioop')

import time
import requests
import json
import os
from datetime import datetime, timedelta
import pytz
import math
import csv

import pandas as pd
import numpy as np

from discord_webhook import DiscordWebhook, DiscordEmbed


# ----------------- CONFIG -----------------
# Your Discord webhook (you asked to include it directly)
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"

# Your Hugging Face token (embedded as requested)
HF_TOKEN = "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"

# Timezone and schedule
TIMEZONE = pytz.timezone("Asia/Karachi")
DAILY_HOUR = 8  # 8 AM PKT daily report
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# Learning / memory file
HISTORY_FILE = "history.csv"  # created/updated by bot

# Model / scoring weights
MODEL_WEIGHT = 0.60   # weight for HF model sentiment output
INDICATOR_WEIGHT = 0.40  # weight for technical indicator confluence

# Price fetch sources (in order)
# Note: some endpoints require headers, handled below
# We use multiple sources to increase reliability
# Function get_gold_price() will try these in order
PRICE_SOURCES = [
    "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",     # Yahoo (primary)
    "https://api.metals.live/v1/spot",                            # metals.live
    "https://data-asg.goldprice.org/dbXRates/USD",                # goldprice.org
    "https://www.goldapi.io/api/XAU/USD"                         # goldapi (needs header token)
]
GOLDAPI_KEY = "goldapi-favtsmgcmdotp-io"  # fallback header for goldapi

# Alert thresholds
ALERT_THRESHOLD = 80  # send alerts only when confidence >= 80
PING_THRESHOLD = 90   # use @everyone if confidence >= 90

# Horizon to evaluate signal outcome for learning (in minutes)
OUTCOME_HORIZON_MIN = 60 * 6  # 6 hours

# ----------------- UTIL: Discord -----------------
webhook = SyncWebhook.from_url(DISCORD_WEBHOOK)

def send_embed(title, description, fields=None, color=0xFFD700, ping_everyone=False):
    """Send a rich embed to Discord. If ping_everyone True, mention everyone at top."""
    content = "@everyone\n" if ping_everyone else None
    embed = Embed(title=title, description=description, color=color, timestamp=datetime.now(TIMEZONE))
    if fields:
        for f in fields:
            embed.add_field(name=f.get("name",""), value=f.get("value",""), inline=f.get("inline", False))
    embed.set_footer(text="Gold AI Smart Bot • Powered by Hasan Ali")
    try:
        webhook.send(content=content, embed=embed)
    except Exception as e:
        print("Discord send error:", e)

# ----------------- PRICE FETCH -----------------
def get_gold_price():
    """Attempt multiple price sources and return a float price or None."""
    # 1) Yahoo Finance (preferred)
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        r = requests.get(url, timeout=8)
        j = r.json()
        price = j["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return float(price)
    except Exception as e:
        print("Yahoo price failed:", e)

    # 2) metals.live
    try:
        r = requests.get("https://api.metals.live/v1/spot", timeout=8)
        j = r.json()
        if isinstance(j, list):
            for d in j:
                if isinstance(d, dict) and "gold" in d:
                    return float(d["gold"])
    except Exception as e:
        print("metals.live failed:", e)

    # 3) goldprice.org (data-asg)
    try:
        r = requests.get("https://data-asg.goldprice.org/dbXRates/USD", timeout=8)
        j = r.json()
        if "items" in j and isinstance(j["items"], list) and len(j["items"])>0:
            return float(j["items"][0]["xauPrice"])
    except Exception as e:
        print("goldprice.org failed:", e)

    # 4) GoldAPI.io (requires header)
    try:
        headers = {"x-access-token": GOLDAPI_KEY}
        r = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=8)
        j = r.json()
        if "price" in j:
            return float(j["price"])
    except Exception as e:
        print("goldapi failed:", e)

    return None

# ----------------- HISTORICAL FETCH (Yahoo) -----------------
def fetch_yahoo_history(period_days=10, interval="60m"):
    """Fetch historical candles from Yahoo to compute indicators."""
    try:
        # request last N days with hourly resolution
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range={period_days}d&interval={interval}"
        r = requests.get(url, timeout=12)
        j = r.json()
        res = j.get("chart", {}).get("result")
        if not res:
            return None
        data = res[0]
        timestamps = data["timestamp"]
        quote = data["indicators"]["quote"][0]
        df = pd.DataFrame({
            "time": pd.to_datetime(timestamps, unit="s"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume")
        })
        df = df.dropna().reset_index(drop=True)
        return df
    except Exception as e:
        print("fetch_yahoo_history error:", e)
        return None

# ----------------- INDICATORS -----------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(window=period, min_periods=1).mean()
    ma_down = down.rolling(window=period, min_periods=1).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))

def atr(df, window=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = (high - low).abs()
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=window, min_periods=1).mean()

# ----------------- HUGGING FACE INFERENCE -----------------
def hf_sentiment(text, model_repo="nlptown/bert-base-multilingual-uncased-sentiment"):
    """
    Call Hugging Face Inference API text classification endpoint.
    Default model is a general sentiment one; you can replace with your trained model repo name.
    Returns (label, score) or (None, 0)
    """
    try:
        url = f"https://api-inference.huggingface.co/models/{model_repo}"
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        payload = {"inputs": text}
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        res = r.json()
        # response formats vary. If list with label & score:
        if isinstance(res, list) and len(res) > 0 and "label" in res[0]:
            label = res[0]["label"]
            score = float(res[0].get("score", 0))
            return label, score
        # for sequence classification returning dict
        if isinstance(res, dict) and "label" in res:
            return res["label"], float(res.get("score", 0))
        # fallback parse if model returns text
        if isinstance(res, dict) and "error" in res:
            print("HF inference error:", res["error"])
            return None, 0
        # sometimes returns string
        if isinstance(res, str):
            return res.strip(), 0.5
    except Exception as e:
        print("HF API error:", e)
    return None, 0.0

# ----------------- CONFLUENCE & CONFIDENCE -----------------
def compute_indicator_confluence(df_latest):
    """
    Compute a 0-100 indicator confluence score using EMA crossover, RSI, ATR proximity to zones.
    df_latest is historical df with indicators computed.
    """
    try:
        close = df_latest['close'].iloc[-1]
        ema20 = ema(df_latest['close'], 20).iloc[-1]
        ema50 = ema(df_latest['close'], 50).iloc[-1]
        rsi_val = rsi(df_latest['close']).iloc[-1]
        atr_val = atr(df_latest).iloc[-1]

        score = 50  # base
        # trend bias
        if ema20 > ema50:
            score += 20
        else:
            score -= 10
        # RSI strong signals
        if rsi_val < 30:
            score += 20
        elif rsi_val > 70:
            score -= 15
        else:
            score += 0

        # volatility adjustment (higher ATR reduces confidence slightly)
        if atr_val and atr_val > 5:  # threshold tuned to dollars scale
            score -= 5

        # clip
        score = max(0, min(100, score))
        return round(score, 2), {"ema20": round(ema20,2), "ema50": round(ema50,2), "rsi": round(rsi_val,2), "atr": round(atr_val,2)}
    except Exception as e:
        print("compute_indicator_confluence error:", e)
        return 50, {}

def combine_confidence(model_score, indicator_score):
    """Combine model (0..1) and indicator (0..100) into final confidence 0..100."""
    # model_score in [0..1] -> map to 0..100
    ms = float(model_score) * 100
    final = MODEL_WEIGHT * ms + INDICATOR_WEIGHT * indicator_score
    return round(final,2)

# ----------------- LEARNING / HISTORY -----------------
def ensure_history_file():
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp","signal","entry_price","direction","confidence","outcome","outcome_checked_at"])
ensure_history_file()

def record_signal(signal_name, entry_price, direction, confidence):
    ts = datetime.utcnow().isoformat()
    ensure_history_file()
    with open(HISTORY_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([ts, signal_name, entry_price, direction, confidence, "", ""])
    print("Recorded signal:", signal_name, direction, entry_price, confidence)

def evaluate_past_signals():
    """
    Iterate open signals and check outcome within OUTCOME_HORIZON_MIN.
    Outcome logic: if direction == 'buy', price rises by X% within horizon -> success.
    We mark +1 for success, -1 for fail, 0 unknown.
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            return
        df = pd.read_csv(HISTORY_FILE)
        updated = False
        for idx, row in df.iterrows():
            if pd.isna(row.get("outcome")) or row.get("outcome")=="":
                ts = datetime.fromisoformat(row["timestamp"])
                entry = float(row["entry_price"])
                direction = row["direction"]
                check_time = ts + timedelta(minutes=OUTCOME_HORIZON_MIN)
                if datetime.utcnow() >= check_time:
                    # fetch price at check_time approx using latest price
                    current_price = get_gold_price()
                    if current_price is None:
                        continue
                    if direction.lower()=="buy":
                        # success if price >= entry * 1.005 (0.5% move up)
                        if current_price >= entry * 1.005:
                            df.at[idx,"outcome"] = "win"
                        else:
                            df.at[idx,"outcome"] = "loss"
                    else:
                        # sell direction success if price <= entry * 0.995
                        if current_price <= entry * 0.995:
                            df.at[idx,"outcome"] = "win"
                        else:
                            df.at[idx,"outcome"] = "loss"
                    df.at[idx,"outcome_checked_at"] = datetime.utcnow().isoformat()
                    updated = True
        if updated:
            df.to_csv(HISTORY_FILE, index=False)
    except Exception as e:
        print("evaluate_past_signals error:", e)

def historical_performance_summary():
    """Return simple stats: wins / total for recent signals"""
    try:
        if not os.path.exists(HISTORY_FILE):
            return {"wins":0,"total":0,"win_rate":0.0}
        df = pd.read_csv(HISTORY_FILE)
        if "outcome" not in df.columns:
            return {"wins":0,"total":0,"win_rate":0.0}
        df_done = df[df["outcome"].notna() & (df["outcome"]!="")]
        total = len(df_done)
        wins = len(df_done[df_done["outcome"]=="win"])
        win_rate = round(wins/total*100,2) if total>0 else 0.0
        return {"wins":wins,"total":total,"win_rate":win_rate}
    except Exception as e:
        print("historical_performance_summary error:", e)
        return {"wins":0,"total":0,"win_rate":0.0}

# ----------------- SIGNAL GENERATION -----------------
def create_signal_and_maybe_alert():
    """Main routine: fetch price, compute features, call HF model for sentiment, compute confidence, alert if >=80%"""
    # fetch current price and history
    price = get_gold_price()
    if price is None:
        print("No price available right now.")
        return

    hist = fetch_yahoo_history(period_days=7, interval="60m")
    if hist is None or hist.empty:
        print("No historical data available for indicators.")
        indicator_score = 50
        indicator_details = {}
    else:
        indicator_score, indicator_details = compute_indicator_confluence(hist)

    # prepare prompt / text for HF inference (we'll ask about buy/sell bias)
    prompt = (
        f"Gold current price is {price:.2f} USD/oz. Indicators: EMA20={indicator_details.get('ema20')}, "
        f"EMA50={indicator_details.get('ema50')}, RSI={indicator_details.get('rsi')}. "
        "Given these, answer Bullish or Bearish and give a probability between 0 and 1 for the next 6 hours."
    )

    # call HF model (use model repo you have or a general sentiment model)
    label, score = hf_sentiment(prompt, model_repo="nlptown/bert-base-multilingual-uncased-sentiment")
    # the chosen repo returns stars 1..5 often; we'll interpret label if possible, otherwise use score
    model_prob = score if score is not None else 0.5

    # If label contains words we can use:
    direction = None
    if label:
        if "positive" in str(label).lower() or "5" in str(label) or "4" in str(label):
            direction = "buy"
        elif "negative" in str(label).lower() or "1" in str(label) or "2" in str(label):
            direction = "sell"

    # combine confidences
    final_conf = combine_confidence(model_prob, indicator_score)

    # include historic performance adjustment (small)
    perf = historical_performance_summary()
    # if historical win_rate low, reduce confidence a bit
    if perf["total"] >= 3:
        # reduce or increase by up to 5%
        if perf["win_rate"] < 50:
            final_conf *= 0.95
        elif perf["win_rate"] > 60:
            final_conf *= 1.03
        final_conf = round(min(100, final_conf),2)

    # decide if we alert: require direction and final_conf >= ALERT_THRESHOLD
    if direction is None:
        # fallback: derive direction from indicator score and EMA
        if indicator_details.get("ema20") and indicator_details.get("ema50"):
            direction = "buy" if indicator_details["ema20"] > indicator_details["ema50"] else "sell"
        else:
            direction = "buy" if indicator_score >= 55 else "sell"

    # generate signal name and record
    signal_name = f"AI_{direction.upper()}_{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    # store signal regardless (we'll evaluate outcomes later)
    record_signal(signal_name, price, direction, final_conf)

    # create friendly embed text
    buy_zone, sell_zone = get_zones(price)
    indicator_lines = "\n".join([f"{k}: {v}" for k,v in indicator_details.items()]) if indicator_details else "N/A"

    description = (
        f"**Price:** ${price:.2f}\n"
        f"**Direction:** {direction.upper()}\n"
        f"**Final Confidence:** {final_conf}%\n\n"
        f"**Buy Zone:** {buy_zone[0] if buy_zone else 'N/A'} – {buy_zone[1] if buy_zone else 'N/A'}\n"
        f"**Sell Zone:** {sell_zone[0] if sell_zone else 'N/A'} – {sell_zone[1] if sell_zone else 'N/A'}\n\n"
        f"**Indicators:**\n{indicator_lines}\n\n"
        f"**AI label:** {label} | model_score={round(model_prob*100,2)}%\n"
        f"**Historical Performance:** wins={perf['wins']} / total={perf['total']} (win_rate={perf['win_rate']}%)"
    )

    # send only if confidence >= ALERT_THRESHOLD
    if final_conf >= ALERT_THRESHOLD:
        ping = final_conf >= PING_THRESHOLD
        title = f"🚨 HIGH CONFIDENCE {direction.upper()} SIGNAL — {final_conf}%"
        fields = [
            {"name":"Details","value":description,"inline":False}
        ]
        send_embed(title, f"Signal: {signal_name}", fields=fields, color=0x2ECC71 if direction=="buy" else 0xE74C3C, ping_everyone=ping)
        print("Alert sent:", signal_name, final_conf)
    else:
        print(f"Signal generated but below threshold ({final_conf}%). Not alerting. Signal: {signal_name}")

# ----------------- DAILY REPORT -----------------
def send_daily_report():
    price = get_gold_price()
    hist = fetch_yahoo_history(period_days=7, interval="60m")
    if hist is None:
        histmsg = "Historical data unavailable."
    else:
        latest = hist['close'].iloc[-1]
        histmsg = f"Latest close (hourly): {latest:.2f}"

    # compute some summary
    perf = historical_performance_summary()
    description = (
        f"Daily AI Forecast — {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        f"Live price: ${price:.2f}\n"
        f"{histmsg}\n\n"
        f"Historical signals: wins={perf['wins']}, total={perf['total']}, win_rate={perf['win_rate']}%\n"
        "Bot monitors every 5 minutes and alerts only for confidence >= 80%.\n"
    )
    send_embed("📊 Daily Gold Forecast & Performance", description, color=0x3498DB)
    print("Daily report sent.")

# ----------------- MAIN LOOP -----------------
def run_bot():
    print("✅ Gold Smart Bot started. Monitoring every", CHECK_INTERVAL_SECONDS, "seconds.")
    # initial send daily report immediately
    try:
        send_daily_report()
    except Exception as e:
        print("Initial daily report error:", e)

    last_daily_date = datetime.now(TIMEZONE).date()

    while True:
        try:
            # evaluate past signals outcomes
            evaluate_past_signals()

            # create signal and maybe alert
            create_signal_and_maybe_alert()

            # daily report check
            now = datetime.now(TIMEZONE)
            if now.hour == DAILY_HOUR and now.date() != last_daily_date:
                try:
                    send_daily_report()
                except Exception as e:
                    print("Daily report error:", e)
                last_daily_date = now.date()

        except Exception as e:
            print("Main loop error:", e)
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_bot()
