# main.py
import requests
import time
import threading
from datetime import datetime, timedelta
import pytz
import schedule
from flask import Flask, jsonify
from bs4 import BeautifulSoup
import pandas as pd

# -----------------------
# CONFIGURATION
# -----------------------
# Replace with your secret values or set as Render environment variables
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
GOLDAPI_KEY = "goldapi-favtsmgcmdotp-io"  # You can replace with env var in Render for safety
TIMEZONE = pytz.timezone("Asia/Karachi")
DAILY_REPORT_HOUR_PAKISTAN = 7  # 7:00 AM PKT
CHECK_INTERVAL_SECONDS = 60  # price check every 1 minute
CONFLUENCE_THRESHOLD = 3  # how strict alerts should be
NEWS_LOOKAHEAD_DAYS = 7
YAHOO_SYMBOL = "GC=F"  # gold futures (used for historicals)

# -----------------------
# FLASK (Render expects a web service to bind)
# -----------------------
app = Flask(__name__)

@app.route("/")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

# -----------------------
# UTIL: Discord embed sender (via webhook)
# -----------------------
def send_discord_embed(title, description=None, fields=None, color=0xFFD700):
    embed = {
        "title": title,
        "description": description or "",
        "color": color,
        "fields": fields or [],
        "timestamp": datetime.utcnow().isoformat()
    }
    payload = {"embeds": [embed]}
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print("Discord send error:", e)

# -----------------------
# PRICE FETCH (GoldAPI with fallback)
# -----------------------
def get_spot_gold_price():
    try:
        headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}
        r = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=10)
        if r.status_code == 200:
            j = r.json()
            return float(j.get("price"))
        else:
            # fallback to Yahoo via quick fetch of latest close from futures
            return fetch_latest_from_yahoo()
    except Exception as e:
        print("GoldAPI error:", e)
        return fetch_latest_from_yahoo()

def fetch_latest_from_yahoo():
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO_SYMBOL}?range=1d&interval=1m"
        r = requests.get(url, timeout=10).json()
        res = r.get("chart", {}).get("result")
        if not res:
            return None
        quotes = res[0]["indicators"]["quote"][0]
        closes = quotes.get("close", [])
        # last non-null close
        for v in reversed(closes):
            if v is not None:
                return float(v)
    except Exception as e:
        print("Yahoo fallback error:", e)
    return None

# -----------------------
# HISTORICAL (for prev day H/L/C and indicators)
# -----------------------
def fetch_historical(days=2, interval="60m"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO_SYMBOL}?range={days}d&interval={interval}"
    try:
        resp = requests.get(url, timeout=15).json()
        res = resp.get("chart", {}).get("result")
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
            "close": quote.get("close")
        })
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print("Historical fetch error:", e)
        return None

# -----------------------
# TECHNICALS: pivots, fibs, indicators
# -----------------------
def daily_pivots(prev_high, prev_low, prev_close):
    pp = (prev_high + prev_low + prev_close) / 3.0
    r1 = (2 * pp) - prev_low
    s1 = (2 * pp) - prev_high
    r2 = pp + (prev_high - prev_low)
    s2 = pp - (prev_high - prev_low)
    return {"PP": round(pp,2), "R1": round(r1,2), "S1": round(s1,2), "R2": round(r2,2), "S2": round(s2,2)}

def fib_levels(high, low):
    diff = high - low
    return {"0.382": round(high - 0.382*diff,2), "0.5": round(high - 0.5*diff,2), "0.618": round(high - 0.618*diff,2)}

def compute_indicators(df):
    # Add EMA50, EMA200, RSI(14), MACD simple
    df = df.copy()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(14).mean()
    ma_down = down.rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + (ma_up / ma_down)))
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    return df

# -----------------------
# FOREXFACTORY scraping for upcoming high impact events
# -----------------------
def fetch_forexfactory_events(limit=10):
    events = []
    try:
        url = "https://www.forexfactory.com/calendar.php"
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # ForexFactory uses rows with class "calendar__row" and impact icons; we gather high impact rows
        rows = soup.select("tr.calendar_row") + soup.select("tr.calendar__row")
        for row in rows:
            # impact high often has class or an image with alt 'High' - be flexible
            impact = row.select_one(".impact")
            if impact and ("High" in impact.get_text() or "high" in impact.get_text().lower()):
                # get time and event text
                time_el = row.select_one(".calendar__time") or row.select_one(".time")
                event_el = row.select_one(".calendar__event") or row.select_one(".calendar__event-title") or row.select_one(".event")
                curr_el = row.select_one(".calendar__currency") or row.select_one(".currency")
                ttext = time_el.get_text(strip=True) if time_el else ""
                etext = event_el.get_text(strip=True) if event_el else row.get_text(strip=True)
                curr = curr_el.get_text(strip=True) if curr_el else ""
                # Filter for USD or global-impact events
                if curr in ("USD", "XAU", "") or "USD" in curr or "All" in curr:
                    events.append(f"{ttext} | {curr} | {etext}")
            if len(events) >= limit:
                break
    except Exception as e:
        print("ForexFactory scrape error:", e)
    return events

# -----------------------
# SENTIMENT (simple engine)
# -----------------------
def get_sentiment():
    # Placeholder; extend by pulling ETF flows, DXY, news sentiment, etc.
    # We'll keep logic simple and adjustable
    fed_tone = "dovish"
    usd = "weak"
    etf_flows = "inflow"
    war_risk = "elevated"

    score = 0
    if fed_tone == "dovish": score += 25
    if usd == "weak": score += 25
    if etf_flows == "inflow": score += 20
    if war_risk == "elevated": score += 20

    bias = "Buy" if score >= 50 else "Neutral"
    confidence = min(100, score + 10)
    details = {"Fed tone": fed_tone, "USD": usd, "ETF flows": etf_flows, "War risk": war_risk}
    return bias, confidence, details

# -----------------------
# Daily report generator
# -----------------------
def generate_and_send_daily_report():
    print("Generating daily report...")
    spot = get_spot_gold_price()
    if spot is None:
        send_discord_embed("⚠️ Gold Report Error", "Could not fetch spot price (both GoldAPI and fallback failed).", color=0xFF0000)
        return

    hist = fetch_historical(days=2, interval="60m")
    if hist is None or hist.empty:
        send_discord_embed("⚠️ Gold Report Error", "Could not fetch historical data.", color=0xFF0000)
        return

    hist = compute_indicators(hist)
    # derive previous calendar day (Pakistan timezone)
    now_pk = datetime.now(TIMEZONE)
    prev_day_date = (now_pk - timedelta(days=1)).date()
    prev_day_df = hist[hist["time"].dt.date == prev_day_date]
    if prev_day_df.empty:
        prev_high = hist["high"].max()
        prev_low = hist["low"].min()
        prev_close = hist["close"].iloc[-1]
    else:
        prev_high = prev_day_df["high"].max()
        prev_low = prev_day_df["low"].min()
        prev_close = prev_day_df["close"].iloc[-1]

    piv = daily_pivots(prev_high, prev_low, prev_close)
    fibs = fib_levels(prev_high, prev_low)
    bias, confidence, sentiment_details = get_sentiment()
    events = fetch_forexfactory_events(limit=8)

    buy_zone_low = fibs["0.618"]
    buy_zone_high = fibs["0.5"]
    sell_zone_low = fibs["0.382"]
    sell_zone_high = piv["R1"]

    # Compose fields
    fields = [
        {"name": "Spot Price (USD)", "value": f"{spot:.2f}", "inline": True},
        {"name": "Bias", "value": bias, "inline": True},
        {"name": "Confidence", "value": f"{confidence}%", "inline": True},
        {"name": "Buy Zone (entry)", "value": f"{buy_zone_low} – {buy_zone_high}", "inline": False},
        {"name": "Sell Zone (entry)", "value": f"{sell_zone_low} – {sell_zone_high}", "inline": False},
        {"name": "Pivot / S1 / S2", "value": f"{piv['PP']} | {piv['S1']} | {piv['S2']}", "inline": False},
        {"name": "R1 / R2", "value": f"{piv['R1']} | {piv['R2']}", "inline": False},
        {"name": "Sentiment details", "value": '\\n'.join([f\"{k}: {v}\" for k, v in sentiment_details.items()]), "inline": False},
    ]

    if events:
        fields.append({"name": "Upcoming High-Impact Events (ForexFactory)", "value": "\\n".join(events), "inline": False})
    else:
        fields.append({"name": "Upcoming High-Impact Events (ForexFactory)", "value": "No major events detected (scrape may be limited).", "inline": False})

    title = f"📊 Gold Daily Forecast — {now_pk.strftime('%Y-%m-%d')} (PKT)"
    send_discord_embed(title, description=f"Daily forecast & buy/sell zones (based on prev day H/L/C + fibs + pivots)", fields=fields, color=0x3498db)
    print("Daily report sent.")

# -----------------------
# Real-time monitor & alerts
# -----------------------
last_sent_zones = {"buy": None, "sell": None}

def check_realtime_and_alert():
    try:
        spot = get_spot_gold_price()
        if spot is None:
            print("Realtime: no price")
            return

        hist = fetch_historical(days=2, interval="60m")
        if hist is None or hist.empty:
            print("Realtime: no hist")
            return
        hist = compute_indicators(hist)
        # get prev day high/low/close
        now_pk = datetime.now(TIMEZONE)
        prev_day_date = (now_pk - timedelta(days=1)).date()
        prev_day_df = hist[hist["time"].dt.date == prev_day_date]
        if prev_day_df.empty:
            prev_high = hist["high"].max()
            prev_low = hist["low"].min()
            prev_close = hist["close"].iloc[-1]
        else:
            prev_high = prev_day_df["high"].max()
            prev_low = prev_day_df["low"].min()
            prev_close = prev_day_df["close"].iloc[-1]

        piv = daily_pivots(prev_high, prev_low, prev_close)
        fibs = fib_levels(prev_high, prev_low)

        # define zones
        buy_low, buy_high = fibs["0.618"], fibs["0.5"]
        sell_low, sell_high = fibs["0.382"], piv["R1"]

        global last_sent_zones

        # BUY zone check
        if buy_low <= spot <= buy_high:
            # If last_sent_zones['buy'] is None or spot has left zone earlier, send
            if last_sent_zones["buy"] is None or (last_sent_zones["buy"] and (datetime.utcnow() - last_sent_zones["buy"]).total_seconds() > 60):
                # send embed
                fields = [
                    {"name": "Price", "value": f"{spot:.2f}", "inline": True},
                    {"name": "Zone", "value": f"{buy_low} – {buy_high}", "inline": True},
                    {"name": "Advice", "value": f"Consider long entries near {buy_low}–{buy_high} with stops below {prev_low}", "inline": False},
                ]
                send_discord_embed("💡 Gold entered BUY zone", description="Professional: Review confluence before manual entry.", fields=fields, color=0x2ecc71)
                last_sent_zones["buy"] = datetime.utcnow()
        else:
            # reset when price leaves zone (so re-entry will trigger again)
            last_sent_zones["buy"] = None

        # SELL zone check
        if sell_low <= spot <= sell_high:
            if last_sent_zones["sell"] is None or (last_sent_zones["sell"] and (datetime.utcnow() - last_sent_zones["sell"]).total_seconds() > 60):
                fields = [
                    {"name": "Price", "value": f"{spot:.2f}", "inline": True},
                    {"name": "Zone", "value": f"{sell_low} – {sell_high}", "inline": True},
                    {"name": "Advice", "value": f"Consider short entries near {sell_low}–{sell_high} with stops above {prev_high}", "inline": False},
                ]
                send_discord_embed("📉 Gold entered SELL zone", description="Professional: Review confluence before manual entry.", fields=fields, color=0xe74c3c)
                last_sent_zones["sell"] = datetime.utcnow()
        else:
            last_sent_zones["sell"] = None

    except Exception as e:
        print("Realtime alert error:", e)

# -----------------------
# Scheduler thread + Flask runner
# -----------------------
def scheduler_thread():
    # daily report at PKT 07:00 -> convert to UTC schedule time
    # PKT = UTC+5, so 07:00 PKT = 02:00 UTC
    utc_report_hour = (DAILY_REPORT_HOUR_PAKISTAN - 5) % 24
    schedule.every().day.at(f"{utc_report_hour:02d}:00").do(generate_and_send_daily_report)
    # price checking every minute
    schedule.every(CHECK_INTERVAL_SECONDS // 60).minutes.do(check_realtime_and_alert)
    # also run once at startup
    generate_and_send_daily_report()
    check_realtime_and_alert()

    while True:
        schedule.run_pending()
        time.sleep(1)

def start_services():
    t = threading.Thread(target=scheduler_thread, daemon=True)
    t.start()
    # run flask app (Render binds to port specified by $PORT environment var)
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("Starting Gold Forecast & Alert Bot...")
    start_services()
