# Quick Setup Guide

## What This Bot Does

This is a **simple Telegram moderation bot** that:
- ✅ Monitors your group chat for TOS-violating content
- ✅ Automatically removes dangerous messages
- ✅ Sends clear notifications explaining why (self-destructs after 30 seconds)
- ✅ Protects your group from being banned by Telegram

**No vouching, no profiles, no complexity** - just pure moderation.

---

## Installation Steps

### 1. Install Python Dependencies

```bash
cd modbot
pip install -r requirements.txt
```

### 2. Create Your Configuration

Copy the example and add your credentials:

```bash
copy .env.example .env
```

Edit `.env` file:
```
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz  # Get from @BotFather
ADMIN_ID=1234567890  # Your Telegram user ID
GROQ_API_KEY=gsk_xxxxxxxxxxxxx  # Optional - for AI moderation
```

**How to get your Telegram User ID:**
- Message [@userinfobot](https://t.me/userinfobot) on Telegram
- It will reply with your ID number

### 3. Run the Bot

```bash
python bot.py
```

You should see:
```
✓ Bot started successfully!
✓ Admin ID: 1234567890
✓ AI Moderation: Enabled
✓ Add this bot to your group as an admin with delete permissions
```

### 4. Add Bot to Your Group

1. Open your Telegram group
2. Click "Add Members"
3. Search for your bot's username
4. Add it to the group
5. **Make it an admin** (required!)
6. Give it permission to **delete messages**

---

## How It Works

1. **User sends a message** with prohibited content (scam link, illegal stuff, etc.)
2. **Bot deletes it immediately**
3. **Bot sends a notification:**
   ```
   ⚠️ Content Removed
   
   Your message was automatically removed to protect this group 
   from being banned by Telegram.
   
   Reason: Scam link detected: bit.ly/free
   
   This message will self-destruct in 30 seconds.
   ```
4. **Notification auto-deletes** after 30 seconds

---

## Commands

- `/start` - Show bot info
- `/help` - Show help message  
- `/stats` - View moderation stats (admin only)

---

## What Gets Removed

The bot removes content that violates Telegram TOS:
- ❌ Scam links (bit.ly/free, crypto pumps, etc.)
- ❌ Illegal content (drugs, weapons, fake documents)
- ❌ Extreme spam/phishing
- ❌ Harassment and threats
- ❌ NSFW content

---

## Customization

Edit `config.py` to customize:
- Add more scam domains to block
- Add keywords to filter
- Change the auto-delete delay
- Customize notification messages

---

## Files Explained

```
modbot/
├── bot.py           # Main bot code (150 lines)
├── moderation.py    # Content checking logic
├── config.py        # Settings and patterns
├── requirements.txt # Python dependencies
├── .env            # Your credentials (create this)
├── .env.example    # Template for .env
└── README.md       # Full documentation
```

---

## Troubleshooting

**Bot doesn't delete messages:**
- Make sure bot is an **admin** in the group
- Make sure bot has **delete messages** permission

**"BOT_TOKEN not set" error:**
- Create `.env` file from `.env.example`
- Add your bot token from @BotFather

**AI not working:**
- AI is optional! Bot works fine without it
- To enable: add `GROQ_API_KEY` to `.env`
- Get free key from: https://console.groq.com

---

## That's It!

Your bot is now protecting your group from Telegram bans. Simple, transparent, effective. 🛡️
