"""
PRIME DIRECTIVE CONFIGURATION
"Protect the Group at All Costs"

The bot's ONLY goal: Prevent the group from being reported and shut down.
No database. No gamification. Just pure protection.
"""
import os
import re
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# BOT CONFIGURATION
# ============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ENABLE_AI_MODERATION = os.getenv("ENABLE_AI_MODERATION", "true").lower() == "true"
FORWARD_GROUP_ID = int(os.getenv("FORWARD_GROUP_ID", "0")) if os.getenv("FORWARD_GROUP_ID") else None

# ============================================================================
# LAYER 1: THE KEYWORD SIEVE (Instant Deletion)
# ============================================================================
# Comprehensive hardcoded list of forbidden terms

# Explicit Drug Names & Slang
DRUG_KEYWORDS = [
    # Hard drugs - Cocaine
    'cocaine', 'coke', 'blow', 'snow', 'charlie', 'flake', 'powder', 'nose candy', 
    'marching powder', 'white', 'yayo', 'yeyo', 'crack cocaine', 'rocks',
    
    # Hard drugs - Methamphetamine
    'meth', 'methamphetamine', 'crystal', 'ice', 'shard', 'gear', 'tina', 'tweek',
    'crank', 'speed', 'glass', 'crystal meth', 'shards', 'spun',
    
    # Hard drugs - Heroin
    'heroin', 'smack', 'dope', 'brown', 'junk', 'horse', 'skag', 'tar',
    'black tar', 'china white', 'heron', 'morphine',
    
    # Hard drugs - Crack/Rock
    'crack', 'rock', 'base', 'rocks', 'crack cocaine',
    
    # Synthetic drugs - MDMA/Ecstasy
    'mdma', 'ecstasy', 'molly', 'pingas', 'pills', 'xtc',
    'rolls', 'ebomb', 'e-bomb', 'adam', 'essence',
    
    # Psychedelics - LSD
    'lsd', 'acid', 'tabs', 'doses', 'blotter', 'trip', 'white tabs', 'purple haze',
    'paper', 'microdots',
    
    # Dissociatives - Ketamine
    'ketamine', 'ket', 'special k', 'cat', 'kitty', 'vitamin k',
    
    # Other drugs
    'ghb', 'liquid ecstasy', 'geebs', 'gee',
    'pcp', 'angel dust', 'dust', 'embalming fluid',
    'fentanyl', 'fent', 'china fentanyl',
    
    # Prescription drugs (abuse context)
    'xanax', 'xans', 'bars', 'benzos', 'benzodiazepines',
    'valium', 'vals', 'diazepam',
    'oxy', 'oxys', 'oxycontin', 'percs', 'percocet', 'vicodin', 'norco',
    'adderall', 'addys', 'amps', 'amphetamines',
    'ritalin', 'methylphenidate',
    'codeine', 'lean', 'purple drank', 'sizzurp', 'syrup', 'lean syrup',
    'hydrocodone', 'tramadol', 'suboxone',
    
    # Cannabis/Marijuana
    'weed', 'marijuana', 'pot', 'grass', 'bud', 'ganja', 'drugs', 'cannabis',
    'hash', 'hashish', 'dope', 'chronic', 'skunk', 'sticky',
    'thc', 'edibles', 'joints', 'blunts', 'spliffs', '420',
    'mary jane', 'mj', 'green', 'flower', 'herb', 'reefer',
    
    # Synthetic cannabinoids
    'spice', 'k2', 'bath salts', 'synthetic weed', 'synthetic cannabis',
    'jwh', 'k3', 'fake weed',
    
    # Other compounds
    '2cb', '2c-b', '2c-e', '2c-i', 'nbome', 'n-bomb',
    'dmt', 'dimethyltryptamine', 'ayahuasca',
    '4-aco-dmt', '5-meo-dmt',
    
    # Inhalants
    'poppers', 'amyl nitrite', 'nitrites', 'rushes',
    
    # Drug-related slang/activities
    'munted', 'munted sausages', 'high', 'stoned', 'blasted', 'wasted', 'tweaked',
    "fred's k", 'put up your nose', 'snort', 'sniff', 'chasing', 'speedball',
    'rails', 'bump', 'shoot up', 'mainline', 'cook',
    'dealing', 'pusher', 'supplier', 'source',
    'score', 'cop', 'grab', 'pick up', 'get some',
]

# Transaction & Supply Terms
TRANSACTION_KEYWORDS = [
    'selling', 'for sale',
    'buying', 'looking for',
    'menu', 'price list', 'prices',
    'drop', 'postage', 'delivery',
    'f2f', 'face to face', 'meet up',
    'escrow',
    'bulk', 'wholesale',
    'sample', 'tester',
    'reup', 're-up', 'restocking',
    'plug', 'connect', 'hookup',
    'vendor', 'supplier',
]

# Scam/Spam/Illegal Services
SCAM_KEYWORDS = [
    'counterfeit', 'fake id', 'fake passport', 'fake documents',
    'money laundering', 'wash money',
    'hacked accounts', 'carded', 'fullz',
    'cvv', 'dumps', 'bins',
    'paypal transfer', 'cashapp flip',
    'western union', 'wu transfer',
    'bitcoin doubler', 'crypto investment',
    'bank logs',
]

# Harassment/Extreme Content (Zero Tolerance)
HARASSMENT_KEYWORDS = [
    'kys', 'kill yourself', 'kill urself',
    'end your life', 'end ur life',
    'you should die', 'you should be dead',
    'go die', 'go kill yourself',
    'rope', 'neck yourself',
]

# MASTER BANNED WORDS LIST (Layer 1 Sieve)
BANNED_WORDS = list(set(
    DRUG_KEYWORDS + 
    TRANSACTION_KEYWORDS + 
    SCAM_KEYWORDS +
    HARASSMENT_KEYWORDS
))

# Suspicious Patterns (Regex for Layer 1)
BANNED_PATTERNS = [
    r't\.me/\+',  # Telegram invite links to other groups
    r'@\w+\s+(menu|prices|selling|vendor)',  # Vendor advertisements
    r'\b(dm|pm)\s+me\s+(for|to|if)',  # DM solicitation
    r'\b(telegram|threema|wickr|signal)\s*:?\s*@?\w+',  # Off-platform contact
    r'\b\d{10,}\b',  # Phone numbers (10+ digits)
    r'\b(btc|eth|xmr|monero)\s*address',  # Crypto wallet solicitation
    r'\$\d+\s*(per|for|each)',  # Pricing
    r'\b(cheap|bulk|wholesale)\s+\w+',  # Bulk sales
]

# ============================================================================
# LAYER 2: THE SEMANTIC NET (AI-Powered Deletion)
# ============================================================================

AI_ANALYSIS_PROMPT = """Analyze this message for the INTENT to buy, sell, or trade illegal goods (like drugs or weapons), promote scams, or share private information.

Respond ONLY with 'VIOLATION' if you are highly confident it violates the rules.
Otherwise respond with 'SAFE'.

Do NOT explain your reasoning. Only respond with one word: VIOLATION or SAFE.

Message to analyze:
"""

# AI Model Configuration
AI_MODEL = "llama-3.1-8b-instant"
AI_TEMPERATURE = 0.1  # Low temperature for consistent responses
AI_MAX_TOKENS = 10  # We only need one word

# ============================================================================
# LAYER 3: THE WATCHER (Behavioral Deletion)
# ============================================================================

# Velocity Control
MAX_MESSAGES_PER_WINDOW = 3
MESSAGE_WINDOW_SECONDS = 5
VELOCITY_MUTE_DURATION = 600  # 10 minutes in seconds

# New User Restrictions
NEW_USER_RESTRICTION_HOURS = 24
RESTRICT_NEW_USER_LINKS = True
RESTRICT_NEW_USER_FORWARDS = True

# ============================================================================
# VOUCH SANITIZATION SYSTEM
# ============================================================================

# Vouch Intent Detection Keywords
VOUCH_KEYWORDS = [
    'pos vouch', 'positive vouch', '+vouch',
    'neg vouch', 'negative vouch', '-vouch',
    'vouch', '+rep', '-rep',
    'solid', 'legend', 'legit',
    'good seller', 'good buyer',
    'trusted', 'trustworthy',
    'scammer', 'scam',
    'recommend', 'do not recommend',
]

# Vouch Detection Pattern (must have vouch keyword + @username in either order)
# Escape special regex characters in keywords
_vouch_keywords_escaped = '|'.join([re.escape(kw).replace(r'\ ', r'\s+') for kw in VOUCH_KEYWORDS])
# Match either: keyword...@username OR @username...keyword
VOUCH_PATTERN = r'(?:(' + _vouch_keywords_escaped + r').*@\w+|@\w+.*(' + _vouch_keywords_escaped + r'))'

# Replacement text for sanitized content
SANITIZE_REPLACEMENT = '[removed]'

# ============================================================================
# USER MESSAGES
# ============================================================================

VOUCH_REPOST_TEMPLATE = """🛡️ **Vouch Record**
From: {author}
Time: {timestamp}

{sanitized_text}

_This vouch is permanently recorded. Even if the account is deleted, this record remains._
"""

VELOCITY_WARNING = """⚠️ **Slow down!**
You're posting too fast. Temporarily muted for 10 minutes to prevent spam.
"""

NEW_USER_WARNING = """⚠️ **New User Restriction**
Users who joined less than 24 hours ago cannot post links or forwards.
This prevents spam bots. Try again tomorrow!
"""

WELCOME_MESSAGE = """🛡️ **Group Protection Bot Active**

**Prime Directive: Protect this group from being shut down.**

**How it works:**
• Messages are scanned instantly for ToS violations
• Obvious violations are deleted in milliseconds
• AI analyzes intent for coded language
• Spam behavior is auto-detected

**Special: Vouch Records System**
• All vouches are recorded with raw data (timestamp, user ID, original text)
• If violations are detected, vouches are sanitized and reposted
• Prohibited words replaced with [removed]
• **Original metadata is preserved** - even if an account is deleted, we keep the record
• This ensures accountability and prevents vouch manipulation

**Rules:**
• No drug sales/buying
• No illegal goods/services
• No scam links
• No spam (max 3 messages per 5 seconds)
• New users (< 24h): no links or forwards

_This bot preserves group integrity through transparent record-keeping._ 🛡️
"""

HELP_MESSAGE = """🛡️ **How This Bot Protects You**

**The Protection System:**

**Layer 1: Keyword Filter**
• Instant deletion of obvious violations
• 100+ banned keywords
• Regex pattern matching

**Layer 2: AI Semantic Analysis**
• Understands coded language and intent
• Catches what keywords miss
• Examples: slang, euphemisms, context

**Layer 3: Behavior Control**
• Max 3 messages per 5 seconds
• New users can't post links for 24h
• Stops spam raids instantly

**Vouch System - Accountability Through Transparency:**
• Every vouch is recorded with raw metadata:
  - Original author username and user ID
  - Exact timestamp
  - Complete original text
• **This data persists even if accounts are deleted**
• Violations are sanitized, not deleted: "the coke was fire" → "the [removed] was fire"
• Reposted immediately with author credit
• Users can search for vouches via @username
• Scammers can't delete their vouch history

**Why This Matters:**
• Prevents reputation manipulation (deleting old vouches)
• Creates permanent accountability
• Protects against account takeovers
• Maintains group integrity

**Commands:**
• `/start` - Show this info
• `/help` - This message

**Transparent. Permanent. Accountable.** 🛡️
"""
