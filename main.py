import sys, types
import time
import requests
from datetime import datetime
import pytz
from discord import SyncWebhook, Embed

# 🩹 Patch for Python 3.13 — fixes missing audioop issue
if 'audioop' not in sys.modules:
    sys.modules['audioop'] = types.ModuleType('audioop')

# ====== CONFIGURATION ======
WEBHOOK_URL = "https://discordapp.com/api/webhooks/1424147591423070302/pP23bHlUs7rEzLVD_0T7kAbrZB8n9rfh-mWsW_S0WXRGpCM8oypCUl0Alg9642onMYON"
TIMEZONE = pytz.timezone("Asia/Karachi")

# ====== FUNCTIONS ======

# --- Gold price fetcher with retry ---
def get_gold_price():
    for _ in range(3):  # Try up to 3 times
        try:
            response = requests.get("https://data-asg.goldprice.org/dbXRates/USD", timeout=5)
            data = response.json()
            return float(data["items"][0]["xauPrice"])
        except Exception:
            time.sleep(2)
    return None

# --- Sentiment Analysis (using ForexFactory calendar sentiment) ---
def get_sentiment():
    try:
        news_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(news_url, timeout=10)
        events = response.json()

        gold_related = [e for e in events if "USD" in e.get("country", "") or "gold" in e.get("title", "").lower()]
        impact_summary = {"High": 0, "Medium": 0, "Low": 0}
        upcoming = []

        for event in gold_related:
            impact = event.get("impact", "Low")
            if impact in impact_summary:
                impact_summary[impact] += 1
            upcoming.append(event.get("title", "Unknown Event"))

        overall = "Neutral"
        if impact_summary["High"] >= 3:
            overall = "Volatile"
        elif impact_summary["Medium"] >= 2:
            overall = "Cautious Bullish"

        return overall, impact_summary, upcoming[:5]

    except Exception:
        return "Unknown", {}, []

# --- Define support/resistance zones dynamically ---
def calculate_zones(price):
    support_zone = round(price - 10, 2)
    resistance_zone = round(price + 10, 2)
    buy_zone = f"{support_zone - 5}–{support_zone}"
    sell_zone = f"{resistance_zone}–{resistance_zone + 5}"
    return buy_zone, sell_zone

# --- Send daily update ---
def send_discord_update():
    price = get_gold_price()
    sentiment, sentiment_details, upcoming = get_sentiment()

    if price:
        buy_zone, sell_zone = calculate_zones(price)
        embed = Embed(
            title="🏆 Daily Gold Forecast",
            description=f"**Live Gold Price:** ${price}\n\n**Sentiment:** {sentiment}",
            color=0xFFD700,
            timestamp=datetime.now(TIMEZONE)
        )
        embed.add_field(name="📈 Buy Zone", value=f"`{buy_zone}`", inline=True)
        embed.add_field(name="📉 Sell Zone", value=f"`{sell_zone}`", inline=True)
        embed.add_field(name="🧠 Sentiment Breakdown", value='\n'.join([f"{k}: {v}" for k, v in sentiment_details.items()]), inline=False)
        embed.add_field(name="📰 Upcoming USD/Gold Events", value="\n".join(upcoming) if upcoming else "No major events.", inline=False)
        embed.set_footer(text="Automated Gold Market Update | Source: ForexFactory & GoldPrice.org")

    else:
        embed = Embed(
            title="⚠️ Could Not Fetch Gold Price",
            description="The system couldn’t retrieve the current gold rate. Will retry in the next cycle.",
            color=0xFF0000,
            timestamp=datetime.now(TIMEZONE)
        )

    webhook = SyncWebhook.from_url(WEBHOOK_URL)
    webhook.send(embed=embed)

# ====== SCHEDULER ======
def run_bot():
    print("✅ Gold Forecast Bot Running 24/7...")
    while True:
        now = datetime.now(TIMEZONE)
        # Run daily report at 7 AM Pakistan time
        if now.hour == 7 and now.minute == 0:
            send_discord_update()
            time.sleep(60)  # Wait 1 min to avoid multiple sends
        else:
            time.sleep(30)

# ====== MAIN EXECUTION ======
if __name__ == "__main__":
    send_discord_update()  # Optional: send one at startup
    run_bot()
