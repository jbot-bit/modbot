#!/usr/bin/env python3
"""Test if the bot token is valid and what user it belongs to"""
import os
import asyncio
from telegram import Bot

async def test():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ BOT_TOKEN not set!")
        return
    
    print(f"Testing token: {token[:30]}...")
    bot = Bot(token=token)
    
    try:
        me = await bot.get_me()
        print(f"✅ Token is VALID!")
        print(f"Bot username: @{me.username}")
        print(f"Bot name: {me.first_name}")
        print(f"Bot ID: {me.id}")
    except Exception as e:
        print(f"❌ Token is INVALID: {e}")

if __name__ == "__main__":
    asyncio.run(test())
