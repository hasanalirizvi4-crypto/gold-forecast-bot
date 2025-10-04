import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

# ========= CONFIG =========
DISCORD_WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL_HERE"  # 👈 paste your webhook URL here
SYMBOL = "XAUUSD"  # Gold
INTERVAL = "1m"    # 1-minute updates
LOOKBACK = "1d"    # look back period
CHECK_INTERVAL = 60  # seconds between checks

# ========= FUNCTIONS =========

def send_discord_message(message: str):
    """Send message to Discord webhook"""
    try:
        data = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=data)
    except Exception as e:
        print("Error sending Discord message:", e)

def get_gold_data():
    """Fetch recent gold price data from Yahoo Finance API"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range={LOOKBACK}&interval={INTERVAL}"
        response = requests.get(url).json()

        timestamps = response['chart']['result'][0]['timestamp']
        prices = response['chart']['result'][0]['indicators']['quote'][0]
        df = pd.DataFrame(prices)
        df['time'] = pd.to_datetime(timestamps, unit='s')
        df = df[['time', 'open', 'high', 'low', 'close']]
        return df
    except Exception as e:
        print("Error fetching data:", e)
        return None

def calculate_indicators(df):
    """Calculate RSI, MACD, and Moving Averages"""
    df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    return df

def fib_levels(high, low):
    """Calculate Fibonacci retracement levels"""
    diff = high - low
    return {
        "0.236": high - 0.236 * diff,
        "0.382": high - 0.382 * diff,
        "0.5": high - 0.5 * diff,
        "0.618": high - 0.618 * diff,
        "0.786": high - 0.786 * diff,
    }

def analyze(df):
    """Analyze market and determine if trade alert should be sent"""
    last = df.iloc[-1]
    prev_high = df['high'].max()
    prev_low = df['low'].min()

    fibs = fib_levels(prev_high, prev_low)
    price = last['close']
    rsi = last['RSI']
    ema20 = last['EMA20']
    ema50 = last['EMA50']
    macd = last['MACD']
    signal = last['Signal']

    alert = None

    # BUY ZONE
    if (price <= fibs["0.618"] and rsi < 30 and ema20 > ema50 and macd > signal):
        alert = f"🟢 **BUY ALERT - GOLD**\nPrice: {price:.2f}\nFib 0.618: {fibs['0.618']:.2f}\nRSI: {rsi:.1f}\nTime: {datetime.utcnow()} UTC"

    # SELL ZONE
    elif (price >= fibs["0.382"] and rsi > 70 and ema20 < ema50 and macd < signal):
        alert = f"🔴 **SELL ALERT - GOLD**\nPrice: {price:.2f}\nFib 0.382: {fibs['0.382']:.2f}\nRSI: {rsi:.1f}\nTime: {datetime.utcnow()} UTC"

    return alert


# ========= MAIN LOOP =========
print("🚀 Gold Trade Alert Bot Started (24/7)")

while True:
    df = get_gold_data()
    if df is not None:
        df = calculate_indicators(df)
        alert = analyze(df)
        if alert:
            send_discord_message(alert)
            print(f"[{datetime.now()}] Alert sent to Discord.")
        else:
            print(f"[{datetime.now()}] No trade zone detected.")
    else:
        print("Data fetch failed.")

    time.sleep(CHECK_INTERVAL)
