"""
Configuration for Telegram Moderation Bot
Replit-optimized: Uses environment variables from Replit secrets
"""
import os

# Bot Configuration - Load from Replit secrets
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Optional AI Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ENABLE_AI_MODERATION = os.getenv("ENABLE_AI_MODERATION", "true").lower() == "true"

# Moderation Settings
AUTO_DELETE_DELAY = int(os.getenv("AUTO_DELETE_DELAY", "15"))  # Seconds - reduced for less spam

# Prohibited Content Patterns - Comprehensive Detection

# Scam & Phishing Domains
SCAM_DOMAINS = [
    # Generic scam patterns
    "bit.ly/free", "tinyurl.com/free", "shorturl.at/free",
    "bit.do/win", "cutt.ly/earn", "rebrand.ly/prize",
    
    # Crypto scams
    "t.me/pump", "telegram.me/crypto", "t.me/airdrop",
    "airdrop-now", "free-bitcoin", "btc-giveaway",
    "eth-airdrop", "crypto-moon", "pump-signal",
    "guaranteed-profit", "100x-gains", "moonshot-alert",
    
    # Financial scams
    "get-rich-quick", "make-money-fast", "passive-income-now",
    "investment-guaranteed", "forex-signals", "trading-bot-free",
    "binary-options-win", "loan-approved-now",
    
    # Phishing
    "verify-account-now", "secure-wallet-update", "claim-reward-here",
    "reset-password-urgent", "account-suspended-fix",
]

# Scam URL patterns (regex)
SCAM_URL_PATTERNS = [
    r"bit\.ly/(?:free|win|earn|prize|claim)",
    r"(?:tinyurl|shorturl|cutt\.ly)/(?:free|crypto|btc|eth)",
    r"t\.me/\w+\?start=[a-zA-Z0-9]{20,}",  # Suspicious referral bots
    r"(?:verify|confirm|secure|update|claim).*(?:account|wallet|prize)",
]

# Banned Keywords - Multi-category (REDUCED TO PREVENT FALSE POSITIVES)
BANNED_KEYWORDS = {
    # --- 1. ILLEGAL GOODS & SUBSTANCES (High-Confidence & Log-Sourced Terms) ---
    "illegal_goods": [
        # **Abbreviations & Direct References (ALWAYS BLOCK)**
        "kys",
        
        # **Cannabis & Marijuana (Transaction-focused only)**
        "buy weed", "weed for sale", "sell weed", "get bud", "thc carts", "buy edibles", "weed drop",

        # **Cocaine & Crack (Transaction-focused only)**
        "buy coke", "coke for sale", "sell cocaine", "coke available", "coke drop", "charlie for sale",

        # **Heroin & Opioids (Transaction-focused only)**
        "buy heroin", "heroin for sale", "fentanyl for sale", "oxy for sale", "sell oxys",

        # **Methamphetamine & Amphetamines**
        "buy meth", "meth for sale", "ice for sale", "shards for sale",

        # **MDMA & Ecstasy**
        "buy mdma", "mdma for sale", "get pingas",

        # **Psychedelics**
        "buy lsd", "lsd for sale", "get shrooms",

        # **Benzodiazepines & Sedatives**
        "buy xanax", "xanax for sale", "get bars", "valium for sale",

        # **Ketamine**
        "buy ket", "ket for sale",

        # **Weapons & Explosives (Transaction-focused)**
        "gun for sale", "buy a gun", "firearm", "handgun", "rifle", "shotgun", "ammo", "ammunition",
        "explosives", "bomb", "c4", "dynamite", "tnt", "ghost gun", "3d printed gun",

        # **Other Illegal (Transaction-focused)**
        "counterfeit money", "fake notes", "cloned cards", "stolen goods", "hot items",
        "ssn", "credit card numbers", "bank logs", "fake passport", "fake id", "fake documents",
        "forged documents", "forged passport", "forged id", "document fraud", "identity fraud",
    ],

    # --- 2. TRANSACTION & INTENT PHRASES (From Logs: "chasing", "drop", "f2f") ---
    "transaction_phrases": [
        "price list", "pricelist",
        "wtb", "w2b",
        "bulk deals", "bulk pricing", "wholesale",
        "re-up", "reup",
        # **Transaction & Intent Phrases (Updated)**
        "meth for sale", "molly for sale", "crack for sale",
    ],

    # --- 3. SPAM, SCAM & MALICIOUS CONTENT ---
    "spam_scam": [
        "get rich quick", "free money", "investment", "guaranteed returns", "ponzi", "pyramid scheme",
        "mlm", "forex", "binary options", "crypto pump", "airdrops", "giveaway", "hacker for hire",
        "ddos", "botnet", "malware", "virus", "phishing", "fake login", "escort", "sex services",
        "hitman", "assassin", "hate speech", "nazi", "racist", "kkk", "supremacy",
        "terrorism", "isis", "jihad", "t.me/+", "t.me/joinchat",
    ],

    # --- 4. EVASION TACTICS (High-Confidence Patterns Only) ---
    "evasion_tactics": [
        # Common slang combinations from logs that are unambiguous
        "on the gear", "on the glass", "hot plate", "sesh",
        # Phrases to evade filters
        "not a cop", "no cops", "discreet drop", "stealth shipping", "no feds", "legit vendor",
        "no time wasters", "serious buyers only",
    ]
}
# Flatten banned keywords for faster lookup
BANNED_KEYWORDS_FLAT = [kw for category in BANNED_KEYWORDS.values() for kw in category]

# Suspicious Patterns - Advanced Regex (CONTEXT-AWARE TO PREVENT FALSE POSITIVES)
SUSPICIOUS_PATTERNS = [
    # Drug transaction context only (requires transaction language)
    r'\b(?:selling|buying|offering|dealing|supply|distribute)\s+(?:cocaine|heroin|meth|fentanyl|mdma|ecstasy|lsd|weed|cannabis|opioid)\b',
    r'\b(?:for|buying|selling)\s+(?:cocaine|heroin|meth|fentanyl|drugs|weed)\b',
    r'\b(?:buy|sell|trade|purchase|selling|offer)\s+(?:drugs|weed|cocaine|heroin|meth|pills|xanax|oxy|fentanyl|mdma|lsd)\b',
    r'\b(?:cocaine|heroin|meth|fentanyl|xanax|oxy|drugs)\s+(?:available|for sale|in stock|pm me|message me|hit me up)\b',
    r'\b(?:been|been\s+buying|been\s+selling|was\s+buying)\s+(?:cocaine|heroin|meth|drugs|weed|fentanyl)\b',
    r'\b\d+(?:\.\d+)?\s*(?:oz|ounce|ounces|gram|kilo|kg|lb)\s+(?:of\s+)?(?:cocaine|heroin|meth|fentanyl|opioid)\b',
    r'\b(?:half|quarter|eighth)\s*(?:oz|ounce|ounces|pound|lb)\s+(?:of\s+)?(?:cocaine|heroin|meth|opioid)\b',
    r'\b(?:quarter\s*pound|qp|qps|eighth|half\s*ounce)\s+(?:cocaine|heroin|meth|weed)\b',
    
    # Counterfeit & illegal documents (transaction context)
    r'\b(?:counterfeit|fake|forged)\s+(?:money|bills|passport|id|license|documents|ssn)\s+(?:for sale|available|selling)\b',
    
    # Hacking & fraud (transaction context)
    r'\b(?:hack|crack|phish|steal|clone)\s+(?:account|password|credit\s*card|bank|wallet|email)\s+(?:for hire|service|available)\b',
    r'\b(?:carding|dumps|fullz|cvv|bins)\s+(?:for sale|available|selling)\b',
    r'\bstolen\s+(?:credit\s*cards?|data|accounts?|identit(?:y|ies))\s+(?:for sale|available|selling)\b',
    
    # CSAM indicators (zero tolerance)
    r'\b(?:cp|child\s*porn|kiddie\s*porn|preteen|underage)\s+(?:content|video|link|pic|photo)\b',
    r'\b(?:young|underage|minor|child|kid)\s+(?:nude|naked|nsfw|porn|xxx)\b',
    
    # Scam patterns (financial context)
    r'\b(?:guaranteed|100%|instant)\s+(?:profit|returns?|money|income)\s+(?:daily|weekly|monthly)\b',
    r'\b(?:double|triple|10x|100x)\s+(?:your\s+)?(?:money|investment|crypto|bitcoin)\s+(?:in|daily|weekly)\b',
    r'(?:send|invest|deposit)\s+\d+.*(?:receive|get|earn)\s+\d+.*(?:back|profit|return)',
    
    # Suspicious crypto (transaction context)
    r'(?:private\s*key|seed\s*phrase|wallet\s*backup)\s+(?:share|send|dm|message)\s+(?:for|to get)\b',
    r'\b(?:trust\s*wallet|metamask|exodus)\s+(?:support|verification|security)\s+(?:help|assist)\b',
    
    # Referral spam (excessive promotion)
    r'(?:click|join|use)\s+(?:my\s+)?(?:ref|referral|invite)\s+(?:link|code).*(?:get|earn|receive|bonus)',
    r't\.me/\w+\?start=\w{20,}',  # Long referral codes
    
    # Gambling promotions (transaction context)
    r'\b(?:casino|gambling|betting|poker)\s+(?:guaranteed|100%|sure)\s+(?:win|profit)\s+(?:strategy|system)\b',
    r'\b(?:bet|gamble|play)\s+(?:and\s+)?(?:win|earn)\s+(?:guaranteed|easy|big)\s+(?:money|cash)\b',
    
    # Pump & dump (transaction context)
    r'\b(?:pump|moon|moonshot|100x)\s+(?:incoming|soon|now|alert|signal)\s+(?:buy|invest|now)\b',
    r'\b(?:buy\s+now|load\s+up|ape\s+in)\s+(?:before|pump|moon)\s+(?:dump|sell)\b',
]

# Telegram invite link patterns (monitor excessive posting)
INVITE_LINK_PATTERN = r"(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)?[\w-]+"

# URL shortener services (often used in scams)
URL_SHORTENERS = [
    "bit.ly", "tinyurl.com", "shorturl.at", "ow.ly", "is.gd",
    "buff.ly", "adf.ly", "bit.do", "mcaf.ee", "su.pr",
    "cutt.ly", "rebrand.ly", "clk.im", "x.co", "goo.gl",
]

# Whitelist - Legitimate content that might match patterns
WHITELIST_PHRASES = [
    "anti-drug campaign", "drug awareness", "say no to drugs",
    "weapon safety", "firearm safety course", "gun control discussion",
    "child protection", "protect children from", "child safety",
    "scam awareness", "avoid scams", "scam alert",
    "bitcoin education", "crypto basics", "blockchain technology",
    "fake news", "fake id in comedy", "counterfeit money in movies",
    "fake passport in movie", "fake id in movie", "forged documents in fiction",
    "kill yourself in video games", "kill yourself in movies", "kys in game", "kys in video game",
    "kill yourself in a video game", "kill yourself in a game", "kill yourself in a movie",
    "mass shooting prevention", "mass shooting awareness",
    "keywords you can't use", "keywords you can use", "banned keywords",
    "drugs are bad", "drug test", "drug prevention",
    "weapons of mass destruction", "weapon safety training",
]

# Rate limiting - Prevent spam
MESSAGE_RATE_LIMIT = 5  # messages per window
RATE_LIMIT_WINDOW = 10  # seconds
LINK_RATE_LIMIT = 3  # links per window
LINK_RATE_WINDOW = 30  # seconds

# Strike system
MAX_STRIKES = 3  # User gets temp muted after 3 violations
STRIKE_RESET_HOURS = 24  # Strikes reset after 24 hours
MUTE_DURATION_MINUTES = 60  # Temp mute for 1 hour

# Messages - Enhanced UX
MODERATION_MESSAGE = """
🛡️ **Content Removed**
@{username}, your message was automatically removed.
**Reason:** {reason}
Removed to protect our community and respect Telegram’s ToS
**Questions?** Contact admin or use /help
_This message will self-destruct in {delay} seconds._
"""

WELCOME_MESSAGE = """
🛡️ **Advanced Moderation Bot Active**

This bot keeps the chat compliant and makes vouching simple.

**✨ How it works:**
• **Automatic Vouch Detection** – Mention someone naturally, and the bot recognizes vouches.
• **/ask @user** – Post a poll to get group feedback.
• **/search @user** – Look up stored vouches before trading.
• **/deletevouch** – Remove your own vouch by replying to it.

**⚡ Smart Moderation:**
✅ Swear words are allowed! Only drugs, scams, and hate speech are banned.
The bot automatically removes content violating Telegram's ToS. Stay safe!
"""

STATS_MESSAGE = """
📊 **Moderation Dashboard**

**📈 Removal Statistics:**
• Total Removed: **{total_removed}** messages
• Last 24 Hours: **{last_24h}** messages
• Vouches Sanitized: **{vouches_sanitized}** 🛡️

**🎯 Top Violation Categories:**
{top_violations}

**⚠️ Severity Breakdown:**
{severity_breakdown}

**👥 User Management:**
• Protected Groups: **{group_count}**
• Users Warned: **{users_warned}**
• Users Muted: **{users_muted}**

_Protecting your community 24/7_
"""

HELP_MESSAGE = """
🛡️ **Bot Commands & Features**

**📝 VOUCHING (Core Feature)**
The bot automatically detects when you mention someone in connection with vouching. You can:
• **Give a vouch naturally**: "pos vouch @user great seller", "+rep @user", "@user is vouched"
• **/neg @user [reason]** – Post a negative vouch for scammers
• **/vouches @user** – Check someone's vouch history before trading
• **/deletevouch** – Reply to YOUR vouch to remove it from history

**� ASKING FOR FEEDBACK**
• **/ask @user** – Create a poll asking if the group vouches for someone
_Perfect when you want group consensus before trading!_

**📊 YOUR ACCOUNT**
• **/mystats** – See your strike history and violation record
• **/start** – Bot overview and welcome message

**⚙️ ADMIN COMMANDS**
• **/stats** – Moderation dashboard (admin only)

**🛡️ HOW MODERATION WORKS**
The bot automatically removes content that violates Telegram's ToS:
❌ Illegal drugs, weapons, scams, fraud, child safety violations, hate speech
✅ Swearing is allowed! General discussion is fine!

**3-Strike System:**
Most violations give you a chance to fix it:
1️⃣ First attempt → Message deleted, 15s warning to rephrase
2️⃣ Second attempt → Final warning, last chance to fix it
3️⃣ Third attempt → Bot automatically cleans it and posts a safe version

**Pro Tips:**
• Speak naturally about traders and vouches – the bot understands context
• Avoid explicit illegal language (use safer terms)
• Drug/scam references in vouches get automatically sanitized to protect the group
• Your vouches are permanently recorded, even if you delete the message

**Questions?** Contact the admin or reply directly to bot messages.
"""

# Sectioned Help Messages for Inline Keyboard
HELP_MAIN = """
🛡️ **Moderation Bot Help**

Choose a section below to learn more:
"""

HELP_VOUCHING = """
📝 **VOUCHING (Core Feature)**

**How to Vouch:**
• Speak naturally: "pos vouch @user great seller"
• Use affirmations: "@user is vouched"
• Negative vouches: "/neg @user [reason]"

**Check History:**
• `/search @user` – See someone's vouch history
• `/deletevouch` – Reply to YOUR vouch to remove it

**Pro Tip:** The bot automatically detects vouches when you mention @users with positive language!
"""

HELP_COMMANDS = """
💬 **COMMANDS & FEATURES**

**Search Vouches:**
• `/search @user` – Look up someone's vouch history

**Get Group Feedback:**
• `/ask @user` – Create a poll asking if the group vouches for someone

**Your Account:**
• `/mystats` – Check your strike history and violations
• `/start` – Bot overview and welcome message

**Admin Only:**
• `/stats` – Moderation dashboard and statistics
"""

HELP_MODERATION = """
🛡️ **MODERATION SYSTEM**

**What Gets Removed:**
❌ Illegal drugs, weapons, scams, fraud
❌ Child safety violations, hate speech
✅ Swearing is allowed! General discussion is fine!

**3-Strike System:**
1️⃣ First violation → Delete + 15s warning to rephrase
2️⃣ Second violation → Delete + final warning
3️⃣ Third violation → Bot auto-cleans and reposts

**Your vouches are permanently recorded** even if the message gets sanitized!
"""

HELP_TIPS = """
💡 **PRO TIPS**

• **Speak naturally** about traders – the bot understands context
• **Avoid explicit illegal language** (use safer terms)
• **Drug references in vouches** get automatically cleaned to protect the group
• **Your vouches stay recorded** even if you delete the message
• **Questions?** Contact the admin or reply to bot messages

**Keep it clean and everyone stays safe!** 🛡️
"""

GUIDE_MESSAGE = """
**Quick reminder** 👋
Just talk naturally about users – we'll track it!
`/ask @user` ➜ poll
`/vouches @user` ➜ history
`/deletevouch` ➜ remove YOUR vouch

Keep it clean. *Msg auto-deletes in 30s.*
"""

GUIDE_POST_INTERVAL_HOURS = 6
GUIDE_DELETE_AFTER_SECONDS = 30


def get_base_webhook_url() -> str:
    """Return the base webhook URL (without token appended).

    This centralizes the WEBHOOK_URL used by `bot_refactored.py` and
    `handle_missed_vouches`. If the environment provides `WEBHOOK_URL`,
    we use it; otherwise fallback to a safe default for Replit.
    """
    base = os.getenv("WEBHOOK_URL")
    if not base:
        return "https://seqmodbot.replit.app/webhook"
    # remove trailing slash to make append consistent
    return base.rstrip("/")


def get_final_webhook_url() -> str:
    """Return full webhook url (with token appended unless already present).

    This central helper ensures `bot_refactored.py` and `handle_missed_vouches`
    use the same final webhook to avoid duplication or mismatch.
    """
    from os import getenv
    base = get_base_webhook_url()
    token = getenv("BOT_TOKEN")
    if token and base.endswith(token):
        return base
    if token:
        # If base already ends with /webhook, append token directly after it
        # Otherwise append /token
        if base.endswith("/webhook"):
            return f"{base}/{token}"
        elif "/" not in base.split("://")[1]:  # No path after domain
            return f"{base}/webhook/{token}"
        else:
            return f"{base}/{token}"
    return base
