"""
Configuration for Telegram Moderation Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
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

# Banned Keywords - Multi-category
BANNED_KEYWORDS = {
    # --- 1. ILLEGAL GOODS & SUBSTANCES (High-Confidence & Log-Sourced Terms) ---
    "illegal_goods": [
        # **Abbreviations & Direct References (ALWAYS BLOCK)**
        "kys", "kill yourself", "kms", "kill myself", "you should die",
        
        # **Cannabis & Marijuana (From Logs: "buds", "gas", "bluntz")**
        "cannabis", "marijuana", "weed", "pot", "buds", "budz", "uds", "ganja", "mary jane",
        "420", "thc", "dank", "dope", "skunk", "reefer", "chronic", "kush", "haze", "indica",
        "sativa", "edibles", "gummies", "thc vape", "dabs", "wax", "shatter", "hash", "hashish",
        "bluntz", "buy weed", "weed for sale", "sell weed", "get bud", "thc carts", "buy edibles", "weed drop",

        # **Cocaine & Crack (From Logs: "rack", "coke", "charlie")**
        "cocaine", "coke", "crack", "blow", "snow", "white girl", "yayo", "charli", "cola",
        "8 ball", "eight ball", "fishscale", "flake", "nose candy", "perico", "rack",
        "buy coke", "coke for sale", "sell cocaine", "coke available", "coke drop", "charlie for sale",

        # **Heroin & Opioids (From Logs: "oxys", "endone", "lean")**
        "heroin", "smack", "gear", "fentanyl", "fent", "fenty", "oxy", "oxys", "oxycontin", "oxycodone",
        "percocet", "percs", "endone", "hydrocodone", "vicodin", "opana", "dilaudid", "morphine",
        "codeine", "sizzurp", "purple drank",
        "buy heroin", "heroin for sale", "fentanyl for sale", "oxy for sale", "sell oxys",

        # **Methamphetamine & Amphetamines (From Logs: "shard", "shards", "dexies", "vyvanse")**
        "meth", "methamphetamine", "crystal", "ice", "shard", "shards", "tina", "tweak", "glass",
        "goey", "phet", "speed", "amphetamine", "dexamphetamine", "dexies", "dexy", "vyvanse",
        "adderall", "ritalin", "buy meth", "meth for sale", "ice for sale", "shards for sale",

        # **MDMA & Ecstasy (From Logs: "pingas", "pingers", "caps")**
        "mdma", "ecstasy", "molly", "mandy", "xtc", "rolls", "beans", "pingas", "pingers",
        "caps", "crystals", "buy mdma", "mdma for sale", "molly for sale", "get pingas",

        # **Psychedelics (From Logs: "shrooms", "acid", "tabs")**
        "lsd", "acid", "tabs", "blotter", "lucy", "shrooms", "mushrooms", "mushies", "psilocybin", "magic mushrooms",
        "dmt", "mescaline", "2cb", "2c-b", "buy lsd", "lsd for sale", "get shrooms",

        # **Benzodiazepines & Sedatives (From Logs: "xanax", "xans", "bars", "vals", "clonz")**
        "xanax", "xans", "zans", "bars", "planks", "footballs", "alprazolam", "valium", "vals",
        "klonopin", "clonazepam", "ativan", "lorazepam", "benzos", "clonz",
        "buy xanax", "xanax for sale", "get bars", "valium for sale",

        # **Ketamine (From Logs: "ket", "k")**
        "ketamine", "ket", "special k", "vitamin k", "horse tranq", "buy ket", "ket for sale",

        # **Weapons & Explosives**
        "gun for sale", "buy a gun", "firearm", "handgun", "rifle", "shotgun", "ammo", "ammunition",
        "explosives", "bomb", "c4", "dynamite", "tnt", "ghost gun", "3d printed gun",

        # **Other Illegals (From Logs: "counterfeit", "fake notes", "cloned cards")**
        "poppers", "amyl nitrate", "nangs", "nitrous", "whippets", "counterfeit", "fake notes",
        "cloned cards", "stolen goods", "hot items", "ssn", "credit card numbers", "bank logs",
        "fake passport", "fake id", "fake documents", "forged documents", "forged passport",
        "forged id", "document fraud", "identity fraud",
    ],

    # --- 2. TRANSACTION & INTENT PHRASES (From Logs: "chasing", "drop", "f2f") ---
    "transaction_phrases": [
        "for sale", "price list", "pricelist",
        "wtb", "w2b",
        "hit me up", "dm me", "pm me", "inbox me",
        "bulk deals", "bulk pricing", "wholesale",
        "how much for",
        "re-up", "reup",
    ],

    # --- 3. SPAM, SCAM & MALICIOUS CONTENT ---
    "spam_scam": [
        "get rich quick", "free money", "investment", "guaranteed returns", "ponzi", "pyramid scheme",
        "mlm", "forex", "binary options", "crypto pump", "airdrops", "giveaway", "hacker for hire",
        "ddos", "botnet", "malware", "virus", "phishing", "fake login", "escort", "sex services",
        "onlyfans", "premium snapchat", "cam girl", "nudes", "leaked", "dox", "doxxing",
        "hitman", "assassin", "hate speech", "nazi", "racist", "kkk", "supremacy",
        "terrorism", "isis", "jihad", "t.me/+", "t.me/joinchat",
    ],

    # --- 4. EVASION TACTICS (High-Confidence Patterns Only) ---
    "evasion_tactics": [
        # REMOVED: Number/symbol obfuscation like c0caine, koke, etc.
        # These are intentional evasion attempts and won't be in BANNED_KEYWORDS_FLAT
        # AI layer will catch most sophisticated obfuscation attempts
        # Only matching exact keywords for high precision
        
        # Common slang combinations from logs that are unambiguous
        "on the gear", "on the glass", "hot plate", "sesh",
        # Phrases to evade filters
        "not a cop", "no cops", "discreet drop", "stealth shipping", "no feds", "legit vendor",
        "no time wasters", "serious buyers only",
    ]
}
# Flatten banned keywords for faster lookup
BANNED_KEYWORDS_FLAT = [kw for category in BANNED_KEYWORDS.values() for kw in category]

# Suspicious Patterns - Advanced Regex
SUSPICIOUS_PATTERNS = [
    # "Lean" in drug context only (purple drank, lean available, etc)
    r"\b(?:purple\s+)?drank\b",  # Purple drank is lean-based
    r"\b(?:lean|sizzurp)\s+(?:available|for sale|in stock|pm me|message me|hit me up)\b",
    
    # Illegal drug transactions (comprehensive variations)
    r"\b(?:have|got|selling|offering)\s+(?:cocaine|heroin|meth|fentanyl|xanax|percocet|oxycodone|oxy|drugs|weed)\b",
    r"\b(?:for|buying|selling)\s+(?:cocaine|heroin|meth|fentanyl|xanax|drugs|weed)\b",
    r"\b(?:buy|sell|trade|purchase|selling|offer)\s+(?:drugs|weed|cocaine|heroin|meth|pills|xanax|oxy|fentanyl|mdma|lsd)\b",
    r"\b(?:cocaine|heroin|meth|fentanyl|xanax|oxy|drugs)\s+(?:available|for sale|in stock|pm me|message me|hit me up)\b",
    r"\b(?:been|been\s+buying|been\s+selling|was\s+buying)\s+(?:cocaine|heroin|meth|drugs|weed|fentanyl)\b",
    r"\b\d+(?:\.\d+)?\s*(?:oz|ounce|ounces)\b",
    r"\b(?:half|quarter)\s*(?:oz|ounce|ounces)\b",
    r"\b(?:quarter\s*pound|qp|qps)\b",
    
    # Counterfeit & illegal documents
    r"\b(?:counterfeit|fake|forged)\s+(?:money|bills|passport|id|license|documents|ssn)\b",
    
    # Hacking & fraud
    r"\b(?:hack|crack|phish|steal|clone)\s+(?:account|password|credit\s*card|bank|wallet|email)\b",
    r"\b(?:carding|dumps|fullz|cvv|bins)\b",
    r"\bstolen\s+(?:credit\s*cards?|data|accounts?|identit(?:y|ies))\b",
    
    # CSAM indicators
    r"\b(?:cp|child\s*porn|kiddie\s*porn|preteen|underage)\s+(?:content|video|link|pic|photo)\b",
    r"\b(?:young|underage|minor|child|kid)\s+(?:nude|naked|nsfw|porn|xxx)\b",
    
    # Scam patterns
    r"\b(?:guaranteed|100%|instant)\s+(?:profit|returns?|money|income)\b",
    r"\b(?:double|triple|10x|100x)\s+(?:your\s+)?(?:money|investment|crypto|bitcoin)\b",
    r"(?:send|invest|deposit)\s+\d+.*(?:receive|get|earn)\s+\d+.*(?:back|profit|return)",
    
    # Suspicious crypto
    r"(?:private\s*key|seed\s*phrase|wallet\s*backup)\s+(?:share|send|dm|message)",
    r"\b(?:trust\s*wallet|metamask|exodus)\s+(?:support|verification|security)\b",
    
    # Referral spam (excessive)
    r"(?:click|join|use)\s+(?:my\s+)?(?:ref|referral|invite)\s+(?:link|code).*(?:get|earn|receive|bonus)",
    r"t\.me/\w+\?start=\w{20,}",  # Long referral codes
    
    # Gambling promotions
    r"\b(?:casino|gambling|betting|poker)\s+(?:guaranteed|100%|sure)\s+(?:win|profit)\b",
    r"\b(?:bet|gamble|play)\s+(?:and\s+)?(?:win|earn)\s+(?:guaranteed|easy|big)",
    
    # Pump & dump
    r"\b(?:pump|moon|moonshot|100x)\s+(?:incoming|soon|now|alert|signal)\b",
    r"\b(?:buy\s+now|load\s+up|ape\s+in)\s+(?:before|pump|moon)",
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
?Y>???? **Advanced Moderation Bot Active**

This bot keeps the chat compliant **and** makes vouching simple.

**?Ys? Commands you need:**
??? /vouch @user note - positive vouch
??? /neg @user note - negative vouch/warning
??? /ask @user - bot posts a poll asking if the user is vouched
??? /vouches @user - see stored vouches

Automated filters still remove anything that breaks Telegram's TOS (illegal goods, harassment, spam, scams). Stay safe & keep it clean!
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
?Y>???? **How to use this group**

**?Y"S Fast vouch workflow**
??? /vouch @user note - record a positive vouch (bot sanitizes risky wording)
??? /neg @user note - record a negative vouch or warning
??? /ask @user - bot posts a quick poll so the group can weigh in
??? /vouches @user - search stored vouches before trading

**?s? Other commands**
??? /start - Bot overview
??? /help - This message
??? /mystats - Your strike history
??? /stats - Moderation dashboard (admin only)

Moderation still removes illegal content, scams, spam, harassment and anything against Telegram TOS. Keep explicit details out of the chat and stay safe. ?Y>????
"""

GUIDE_MESSAGE = """
**Quick reminder**
`/vouch @user note` \u2192 positive vouch
`/neg @user note` \u2192 warning
`/ask @user` \u2192 poll
`/vouches @user` \u2192 history

Keep it clean so the bot won\'t sanitize or delete. *Msg auto-deletes in 30s.*
"""

GUIDE_POST_INTERVAL_HOURS = 6
GUIDE_DELETE_AFTER_SECONDS = 30
