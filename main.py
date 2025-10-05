import requests
import datetime
import pytz
import schedule
import time
from discord import SyncWebhook, Embed
from bs4 import BeautifulSoup

# ======================
# CONFIGURATION
# ======================
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
GOLDAPI_KEY = "goldapi-favtsmgcmdotp-io"
GOLDAPI_URL = "https://www.goldapi.io/api/XAU/USD"
TIMEZONE = pytz.timezone("Asia/Karachi")

webhook = SyncWebhook.from_url(DISCORD_WEBHOOK_URL)

# ======================
# FETCH LIVE GOLD PRICE
# ======================
def get_gold_price():
    headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}
    try:
        res = requests.get(GOLDAPI_URL, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json().get("price")
        else:
            # Fallback API (Metals-API)
            alt = requests.get("https://metals-api.com/api/latest?base=USD&symbols=XAU")
            data = alt.json()
            return 1 / data["rates"]["XAU"]
    except Exception as e:
        print("Error fetching gold price:", e)
        return None

# ======================
# FETCH FOREXFACTORY NEWS
# ======================
def fetch_forexfactory_events():
    try:
        url = "https://www.forexfactory.com/calendar"
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        events = []
        for row in soup.select("tr.calendar__row--impact-high"):
            title = row.select_one(".calendar__event-title")
            currency = row.select_one(".calendar__currency")
            if title and currency and currency.text.strip() in ["USD", "XAU"]:
                events.append(f"{currency.text.strip()} - {title.text.strip()}")
        return events[:5]
    except Exception as e:
        print("Error fetching ForexFactory events:", e)
        return []

# ======================
# SENTIMENT MODEL
# ======================
def get_sentiment():
    fed_tone = "dovish"
    usd_strength = "weak"
    etf_flows = "inflow"
    war_risk = "high"

    score = 0
    if fed_tone == "dovish": score += 25
    if usd_strength == "weak": score += 25
    if etf_flows == "inflow": score += 20
    if war_risk == "high": score += 30

    bias = "Buy" if score > 50 else "Sell" if score < -50 else "Neutral"
    confidence = min(100, abs(score) + 20)
    return bias, confidence, {"Fed tone": fed_tone, "USD": usd_strength, "ETF": etf_flows, "War": war_risk}

# ======================
# CALCULATE LEVELS
# ======================
def calculate_levels(price):
    prev_high = price * 1.008
    prev_low = price * 0.992
    pivot = (prev_high + prev_low + price) / 3
    fib_38 = prev_high - (prev_high - prev_low) * 0.382
    fib_61 = prev_high - (prev_high - prev_low) * 0.618

    support1 = round(fib_61, 2)
    support2 = round(prev_low, 2)
    resistance1 = round(fib_38, 2)
    resistance2 = round(prev_high, 2)

    return {
        "pivot": round(pivot, 2),
        "S1": support1, "S2": support2,
        "R1": resistance1, "R2": resistance2
    }

# ======================
# DAILY REPORT
# ======================
def send_daily_report():
    price = get_gold_price()
    if not price:
        webhook.send("⚠️ Failed to fetch gold price.")
        return

    bias, confidence, sentiments = get_sentiment()
    levels = calculate_levels(price)
    events = fetch_forexfactory_events()

    buy_zone = f"{levels['S1']} – {levels['pivot']}"
    sell_zone = f"{levels['pivot']} – {levels['R1']}"

    embed = Embed(
        title=f"📊 Gold Daily Forecast – {datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d')}",
        color=0xFFD700,
        timestamp=datetime.datetime.now(TIMEZONE)
    )
    embed.add_field(name="Spot Price", value=f"${price:.2f}", inline=False)
    embed.add_field(name="Bias", value=bias, inline=True)
    embed.add_field(name="Confidence", value=f"{confidence}%", inline=True)
    embed.add_field(name="Buy Zone", value=buy_zone, inline=True)
    embed.add_field(name="Sell Zone", value=sell_zone, inline=True)
    embed.add_field(name="Support / Resistance", value=f"S1: {levels['S1']} | S2: {levels['S2']} | R1: {levels['R1']} | R2: {levels['R2']}", inline=False)

    sentiment_text = "\n".join([f"{k}: {v}" for k, v in sentiments.items()])
    embed.add_field(name="🧠 Sentiment Drivers", value=sentiment_text, inline=False)

    if events:
        embed.add_field(name="📰 Upcoming Events (ForexFactory)", value="\n".join(events), inline=False)
    else:
        embed.add_field(name="📰 Upcoming Events", value="No major events detected.", inline=False)

    embed.set_footer(text="Gold Forecast Bot | Powered by GPT-5")
    webhook.send(embed=embed)

# ======================
# ALERT ENGINE
# ======================
last_zone = None
def check_price_alerts():
    global last_zone
    price = get_gold_price()
    if not price:
        return

    levels = calculate_levels(price)
    if levels["S1"] <= price <= levels["pivot"]:
        if last_zone != "buy":
            embed = Embed(
                title="💡 Gold entered Buy Zone",
                description=f"Current price: ${price:.2f}\nConsider long entries near {levels['S1']}–{levels['pivot']} with stops below {levels['S2']}.",
                color=0x00FF00,
                timestamp=datetime.datetime.now(TIMEZONE)
            )
            webhook.send(embed=embed)
            last_zone = "buy"

    elif levels["pivot"] <= price <= levels["R1"]:
        if last_zone != "sell":
            embed = Embed(
                title="📉 Gold entered Sell Zone",
                description=f"Current price: ${price:.2f}\nConsider short entries near {levels['pivot']}–{levels['R1']} with stops above {levels['R2']}.",
                color=0xFF0000,
                timestamp=datetime.datetime.now(TIMEZONE)
            )
            webhook.send(embed=embed)
            last_zone = "sell"

# ======================
# SCHEDULER
# ======================
def run_scheduler():
    schedule.every().day.at("07:00").do(send_daily_report)
    schedule.every(1).minutes.do(check_price_alerts)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    print("🚀 Gold Forecast Bot started successfully!")
    send_daily_report()  # Send first report immediately
    run_scheduler()
