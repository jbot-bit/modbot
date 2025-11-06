"""
Helper script to clear any existing Telegram webhooks
Run this if you're getting conflict errors from another bot instance
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ BOT_TOKEN not found in environment variables")
    exit(1)

# Clear webhook
url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
response = httpx.get(url)

print("🔧 Clearing Telegram webhook...")
print(f"Response: {response.json()}")

if response.json().get("ok"):
    print("✅ Webhook cleared successfully!")
    print("✅ You can now run the bot with: python bot.py")
else:
    print("❌ Failed to clear webhook")
    print(response.json())
