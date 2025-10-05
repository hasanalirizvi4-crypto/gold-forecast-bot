import requests
import schedule
import time
from datetime import datetime, timedelta
import pytz

# === CONFIG ===
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
TIMEZONE = pytz.timezone("Asia/Karachi")
SYMBOL = "XAU/USD"

# === FUNCTION TO FETCH GOLD PRICE ===
def get_gold_price():
    try:
        url = "https://api.metals.live/v1/spot/gold"
        res = requests.get(url, timeout=10)
        data = res.json()
        price = data[0]['price'] if isinstance(data, list) else data.get('price')
        return float(price)
    except Exception as e:
        print("Error fetching gold price:", e)
        return None

# === FOREXFACTORY NEWS (SIMPLIFIED) ===
def get_upcoming_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        res = requests.get(url, timeout=10)
        news_data = res.json()
        events = [f"{i['title']} ({i['impact']}) on {i['date']}" for i in news_data if "Gold" in i.get('title', '') or "USD" in i.get('currency', '')]
        return events[:5] if events else ["No major events."]
    except:
        return ["Could not fetch news."]

# === MARKET SENTIMENT (SIMPLIFIED MODEL) ===
def analyze_sentiment(price):
    if price > 2400:
        sentiment = "🟢 Bullish"
        reasons = {
            "Fed stance": "Expected rate cuts boost gold",
            "USD trend": "Dollar weakening supports metals",
            "ETF inflows": "Positive",
            "Risk sentiment": "Investors hedging geopolitical tension",
        }
    elif price < 2300:
        sentiment = "🔴 Bearish"
        reasons = {
            "Fed stance": "Rates stable or rising",
            "USD trend": "Stronger dollar hurting gold",
            "ETF flows": "Outflows",
            "Market mood": "Less fear, reduced safe-haven demand",
        }
    else:
        sentiment = "🟡 Neutral"
        reasons = {
            "Fed stance": "Mixed comments",
            "USD trend": "Range-bound",
            "ETF flows": "Steady",
            "Risk sentiment": "Unclear direction",
        }
    return sentiment, reasons

# === DAILY BUY/SELL ZONES ===
def generate_zones(price):
    support = round(price - 15, 2)
    resistance = round(price + 15, 2)
    buy_zone = (support - 5, support + 3)
    sell_zone = (resistance - 3, resistance + 5)
    return support, resistance, buy_zone, sell_zone

# === SEND TO DISCORD ===
def send_discord_embed(title, description, fields):
    embed = {
        "title": title,
        "description": description,
        "color": 0xF1C40F,
        "fields": fields,
        "timestamp": datetime.now().isoformat()
    }
    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})

# === DAILY REPORT JOB ===
def send_daily_report():
    price = get_gold_price()
    if not price:
        print("Failed to fetch gold price.")
        return

    sentiment, sentiment_details = analyze_sentiment(price)
    support, resistance, buy_zone, sell_zone = generate_zones(price)
    news = get_upcoming_news()

    fields = [
        {"name": "Current Price", "value": f"${price}", "inline": True},
        {"name": "Sentiment", "value": sentiment, "inline": True},
        {"name": "Support", "value": f"{support}", "inline": True},
        {"name": "Resistance", "value": f"{resistance}", "inline": True},
        {"name": "Buy Zone", "value": f"{buy_zone[0]} - {buy_zone[1]}", "inline": False},
        {"name": "Sell Zone", "value": f"{sell_zone[0]} - {sell_zone[1]}", "inline": False},
        {"name": "Sentiment details", "value": '\n'.join([f"{k}: {v}" for k, v in sentiment_details.items()]), "inline": False},
        {"name": "Upcoming News", "value": '\n'.join(news), "inline": False},
    ]

    send_discord_embed("📊 Daily Gold Market Report", f"Analysis for {SYMBOL}", fields)
    print("✅ Daily report sent.")

# === ZONE ALERTS ===
def check_price_zones():
    price = get_gold_price()
    if not price:
        return
    _, _, buy_zone, sell_zone = generate_zones(price)

    if buy_zone[0] <= price <= buy_zone[1]:
        send_discord_embed("🟩 BUY Opportunity", f"Gold entered buy zone near {price}", [])
    elif sell_zone[0] <= price <= sell_zone[1]:
        send_discord_embed("🟥 SELL Opportunity", f"Gold entered sell zone near {price}", [])

# === SCHEDULER ===
def run_scheduler():
    schedule.every().day.at("07:00").do(send_daily_report)
    schedule.every(1).hours.do(check_price_zones)

    print("✅ Bot running... waiting for 7 AM PKT report")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    run_scheduler()
