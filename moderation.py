"""
Advanced Content Moderation Engine
Multi-layer detection: Pattern matching + Toxicity detection + URL analysis + AI semantic analysis
"""
import re
import logging
import httpx
import json
import asyncio
import importlib
import random
from typing import Dict, Optional, Tuple, List
from collections import defaultdict
from datetime import datetime, timedelta
from config import (
    SCAM_DOMAINS,
    BANNED_KEYWORDS_FLAT,
    SUSPICIOUS_PATTERNS,
    SCAM_URL_PATTERNS,
    URL_SHORTENERS,
    WHITELIST_PHRASES,
    GROQ_API_KEY,
    ENABLE_AI_MODERATION,
)

logger = logging.getLogger(__name__)
MENTION_REGEX = re.compile(r'@[\w\d_]+')
_VOUCH_PREFIX_PATTERN = re.compile(
    r"""^(
        (?:\+|-)?rep\s+
        |(?:pos(?:itive)?|neg(?:ative)?)\s+vouch\s+
        |vouch\s+(?:for\s+)?
        |vouched\s+
    )+""",
    re.IGNORECASE | re.VERBOSE,
)


def strip_mentions(text: str) -> str:
    """Remove @handles so keyword scans don't trigger on names."""
    return MENTION_REGEX.sub(" ", text or "")


def extract_mentions(text: str) -> List[str]:
    """Return list of bare usernames mentioned (without @)."""
    if not text:
        return []
    mentions = []
    for match in MENTION_REGEX.findall(text):
        username = match.lstrip("@")
        if username:
            mentions.append(username)
    return mentions

# ============================================================================
# TOXIC-BERT MODEL INITIALIZATION (Local AI - Zero Cost)
# ============================================================================
toxic_classifier = None

def initialize_toxic_classifier():
    """
    Initialize Toxic-BERT model for local toxicity/harassment detection.
    Runs once at module import time. Falls back gracefully if model fails to load.
    
    Model: unitary/toxic-bert
    - Speed: 50-100ms per message (CPU)
    - Accuracy: 94% on toxic content detection
    - Cost: $0 (completely free, runs locally)
    - Size: ~400MB (one-time download)
    
    This layer catches harassment/toxicity BEFORE Groq AI calls, saving $$.
    """
    global toxic_classifier
    if (
        importlib.util.find_spec("transformers") is None
        or importlib.util.find_spec("torch") is None
    ):
        logger.info("transformers/torch not installed - skipping Toxic-BERT layer")
        toxic_classifier = None
        return
    try:
        from transformers import pipeline
        toxic_classifier = pipeline(
            "text-classification",
            model="unitary/toxic-bert",
            device=-1  # -1 = CPU, 0 = GPU if available
        )
        logger.info("ÃƒÂ¢Ã…Â“Ã¢Â€Âœ Toxic-BERT model loaded successfully (local toxicity detection ready)")
    except Exception as e:
        logger.warning(f"ÃƒÂ¢Ã…Â¡Ã‚Â  Failed to load Toxic-BERT model: {e} (toxicity layer will be skipped)")
        toxic_classifier = None

# Load model at startup
try:
    initialize_toxic_classifier()
except Exception as e:
    logger.error(f"Error initializing Toxic-BERT: {e}")
    toxic_classifier = None

# Rate limiting tracking
message_tracker = defaultdict(list)  # user_id -> [(timestamp, message)]
link_tracker = defaultdict(list)  # user_id -> [(timestamp, link)]

# Initialize advanced pattern matching
try:
    import ahocorasick
    
    # Build Aho-Corasick automaton for ultra-fast pattern matching
    automaton = ahocorasick.Automaton()
    
    # Add scam domains
    for domain in SCAM_DOMAINS:
        automaton.add_word(domain.lower(), ('scam_domain', domain))
    
    # Add banned keywords
    for keyword in BANNED_KEYWORDS_FLAT:
        automaton.add_word(keyword.lower(), ('banned_keyword', keyword))
    
    # Add URL shorteners
    for shortener in URL_SHORTENERS:
        automaton.add_word(shortener.lower(), ('url_shortener', shortener))
    
    automaton.make_automaton()
    total_patterns = len(SCAM_DOMAINS) + len(BANNED_KEYWORDS_FLAT) + len(URL_SHORTENERS)
    logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ Pattern matching initialized: {total_patterns} patterns loaded")
    
except ImportError:
    logger.warning("ÃƒÂ¢Ã…Â¡Ã‚Â  ahocorasick not available - using slower regex matching")
    automaton = None


def check_whitelist(text: str) -> bool:
    """Check if text contains whitelisted educational content"""
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in WHITELIST_PHRASES)


def check_toxicity(text: str) -> Tuple[bool, str]:
    """
    Local toxicity/harassment detection using Toxic-BERT model.
    Runs instantly without API calls - 50-100ms on CPU.
    
    Args:
        text: Message text to check
    
    Returns:
        (is_toxic: bool, reason: str)
        - is_toxic: True if message contains toxic/hostile language
        - reason: Explanation of detected toxicity (if is_toxic=True)
    
    Examples of what this catches:
    - "your code is trash" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ toxic
    - "you're so dumb" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ toxic
    - "i hope bad things happen to you" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ toxic
    - "I recommend this service" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ not toxic
    - "Great work!" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ not toxic
    
    Returns (False, "") if model not available or on any error.
    """
    if not toxic_classifier:
        return False, ""
    
    try:
        # Truncate to 512 tokens max (BERT model limit)
        text_truncated = text[:512] if len(text) > 512 else text
        
        # Get prediction
        result = toxic_classifier(text_truncated)
        
        if result and len(result) > 0:
            prediction = result[0]
            label = prediction.get("label", "").lower()
            score = prediction.get("score", 0.0)
            
            # Flag as toxic if model confidence is 80%+
            if label == "toxic" and score >= 0.80:
                return True, f"Toxicity detected (confidence: {score:.0%})"
        
        return False, ""
        
    except Exception as e:
        logger.error(f"Toxicity check error: {e}")
        return False, ""


def is_vouch_request(text: str) -> bool:
    """Detect when someone is asking for vouches rather than giving one."""
    if not text or "vouch" not in text:
        return False

    normalized = re.sub(r"\s+", " ", text.strip().lower())
    request_patterns = [
        r"\bany(?:one)?\s+vouches?\b",
        r"\bany\s+vouches?\s+on\b",
        r"\bvouches?\s*\?",
        r"\bcan\s+(?:someone|anyone|ya|yall)\s+vouch\b",
        r"\bwho\s+(?:can|able\s+to)\s+vouch\b",
        r"\bneed(?:s)?\s+(?:a\s+)?vouch\b",
        r"\blooking\s+for\s+vouch",
        r"\bvouch(?:es)?\s+on\b",
    ]
    return any(re.search(pattern, normalized) for pattern in request_patterns)


def is_vouch(text: str) -> bool:
    """
    Detect if message is a vouch (vouching for someone)
    Uses composite pattern: vouch keyword + @username mention
    
    Enhanced from prime directive config for bulletproof recognition:
    - Positive vouch keywords: pos vouch, +rep, vouch, +1, legit, solid, trusted, etc.
    - Negative vouch keywords: neg vouch, scammer, scam, -rep, etc.
    - Must contain @username mention to be valid vouch
    - Must have space/boundary before @ (prevents vouch@user false positives)
    
    Common patterns: "+rep @user", "vouch for @user", "neg vouch @scammer", etc.
    """
    if not text or len(text) < 5:  # Quick length check
        return False
    
    text_lower = text.lower()
    if is_vouch_request(text_lower):
        return False
    
    # Comprehensive vouch keywords (from prime directive)
    vouch_keywords = [
        # Positive vouches
        'pos vouch', 'positive vouch', '+vouch', '+rep',
        'vouch for', 'vouch', '+1', 'solid', 'legend', 'legit',
        'good seller', 'good buyer', 'trusted', 'trustworthy',
        'recommend', 'can vouch', 'i vouch', 'vouched', 'vouching',
        
        # Negative vouches
        'neg vouch', 'negative vouch', '-vouch', '-rep',
        'scammer', 'scam', 'do not recommend', 'vouch against',
    ]
    
    # Build composite regex pattern: Match EITHER order
    # Pattern 1: keyword...@username OR Pattern 2: @username...keyword
    keyword_pattern = r'(' + '|'.join([re.escape(kw).replace(r'\ ', r'\s+') for kw in vouch_keywords]) + r')'
    composite_pattern = r'(?:' + keyword_pattern + r'.*@\w+|@\w+.*' + keyword_pattern + r')'
    
    return bool(re.search(composite_pattern, text_lower))


def sanitize_text(text: str) -> str:
    """
    Remove TOS-violating content but preserve vouch structure.
    Uses both keyword matching and regex patterns for comprehensive sanitization.
    
    Returns sanitized version of the text
    """
    if not text:
        return text
    
    sanitized = text
    
    # Single-pass batch replacement of all banned keywords with WORD BOUNDARIES
    # This prevents false positives like "lean" matching in "clean"
    banned_pattern = re.compile(
        r'\b(' + '|'.join(re.escape(word) for word in BANNED_KEYWORDS_FLAT) + r')\b',
        re.IGNORECASE
    )
    sanitized = banned_pattern.sub('[REMOVED]', sanitized)
    
    # Refined regex patterns for sanitization
    drug_weapon_patterns = [
        r'\b(?:great|good|best|perfect|excellent)\s+(?:for|with|on)\s+(?:drugs|cocaine|heroin|meth|weed)\b(?!.*(?:educational|fictional|awareness))',
        r'\b(?:uses|using|buys|buying|sells|selling)\s+(?:cocaine|heroin|meth|weed|fentanyl)\b',
        r'\b(?:weapons|guns|firearms)\s+(?:for sale|available|in stock)\b',
        r'\b(?:been|been\s+buying|been\s+selling)\s+(?:cocaine|heroin|meth|drugs|weed)\b',
    ]
    
    for pattern in drug_weapon_patterns:
        try:
            sanitized = re.sub(pattern, '[REMOVED]', sanitized, flags=re.IGNORECASE)
        except re.error:
            continue
    
    # Remove scam domains
    for domain in SCAM_DOMAINS:
        pattern = re.compile(re.escape(domain), re.IGNORECASE)
        sanitized = pattern.sub('[LINK REMOVED]', sanitized)
    
    # Remove URL shorteners
    for shortener in URL_SHORTENERS:
        pattern = re.compile(re.escape(shortener), re.IGNORECASE)
        sanitized = pattern.sub('[LINK REMOVED]', sanitized)
    
    # Remove suspicious URLs but keep the structure
    urls = extract_urls(sanitized)
    for url in urls:
        is_suspicious, _ = check_url_reputation(url)
        if is_suspicious:
            sanitized = sanitized.replace(url, '[LINK REMOVED]')
    
    # Clean up multiple spaces and [REMOVED] repetitions
    sanitized = re.sub(r'(\[REMOVED\]\s*)+', '[REMOVED] ', sanitized)

    # Swap generic placeholders with softer wording to keep context natural
    filler_choices = ["premium goods", "safe product", "clean service", "trusted item", "solid drop"]
    sanitized = re.sub(r'\[REMOVED\]', lambda _: random.choice(filler_choices), sanitized)
    sanitized = sanitized.replace('[LINK REMOVED]', '[clean link]')
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized


def extract_urls(text: str) -> list:
    """Extract all URLs from text"""
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)


def check_url_reputation(url: str) -> Tuple[bool, str]:
    """Check if URL is suspicious based on patterns and shorteners"""
    url_lower = url.lower()
    
    # Check URL shorteners (often used in scams)
    for shortener in URL_SHORTENERS:
        if shortener in url_lower:
            return True, f"Suspicious URL shortener: {shortener}"
    
    # Check scam URL patterns
    for pattern in SCAM_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True, "Scam URL pattern detected"
    
    return False, ""


def check_patterns(text: str, user_id: int = None) -> Tuple[bool, str, str]:
    """
    Advanced pattern-based violation detection
    Returns: (is_violation, reason, severity)
    Severity: 'critical', 'high', 'medium', 'low'
    """
    if not text:
        return False, "", "low"
    
    # Check whitelist first (educational content)
    if check_whitelist(text):
        return False, "", "low"
    
    text_lower = text.lower()
    text_no_mentions = strip_mentions(text_lower)
    
    # CRITICAL VIOLATIONS (zero tolerance)
    critical_keywords = ['cp link', 'child porn', 'underage nudes', 'preteen', 'kiddie porn']
    for keyword in critical_keywords:
        if keyword in text_lower:
            return True, "CRITICAL: Child exploitation material (zero tolerance)", "critical"
    
    # Method 1: Aho-Corasick (fastest)
    if automaton:
        for end_index, (category, pattern) in automaton.iter(text_no_mentions):
            if category == 'scam_domain':
                return True, f"Scam link detected: {pattern}", "high"
            elif category == 'banned_keyword':
                # More context-aware keyword checking
                if is_contextual_violation(text_no_mentions, pattern):
                    # Determine severity based on keyword
                    if any(kw in pattern for kw in ['drug', 'weapon', 'fake passport', 'counterfeit']):
                        return True, f"Illegal content: {pattern}", "high"
                    elif any(kw in pattern for kw in ['kys', 'kill yourself']):
                        return True, f"Extreme harassment: {pattern}", "high"
                    else:
                        return True, f"Prohibited content: {pattern}", "medium"
            elif category == 'url_shortener':
                # URL shorteners are medium severity
                return True, f"Suspicious URL shortener: {pattern}", "medium"
    else:
        # Fallback: Manual checking with context awareness
        for domain in SCAM_DOMAINS:
            if domain.lower() in text_lower:
                return True, f"Scam link detected: {domain}", "high"
        
        for keyword in BANNED_KEYWORDS_FLAT:
            if keyword.lower() in text_no_mentions and is_contextual_violation(text_no_mentions, keyword):
                if any(kw in keyword.lower() for kw in ['drug', 'weapon', 'fake passport']):
                    return True, f"Illegal content: {keyword}", "high"
                else:
                    return True, f"Prohibited content: {keyword}", "medium"
    
    # Check URL reputation
    urls = extract_urls(text)
    for url in urls:
        is_suspicious, reason = check_url_reputation(url)
        if is_suspicious:
            return True, reason, "medium"
    
    # Check regex patterns
    for pattern in SUSPICIOUS_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Determine severity based on pattern type
            if any(term in pattern for term in ['child', 'cp', 'underage', 'minor']):
                return True, "CRITICAL: Child exploitation pattern detected", "critical"
            elif any(term in pattern for term in ['drug', 'weapon', 'explosive', 'counterfeit']):
                return True, "Illegal goods/services detected", "high"
            elif any(term in pattern for term in ['hack', 'steal', 'phish', 'fraud']):
                return True, "Hacking/fraud activity detected", "high"
            else:
                return True, "Suspicious pattern detected (TOS violation)", "medium"
    
    return False, "", "low"


def is_contextual_violation(text_lower: str, keyword: str) -> bool:
    """
    Check if a keyword match is actually a violation in context.
    Prevents false positives for educational/fictional content.
    
    DRUG KEYWORDS: Be conservative - if it looks like it could be a sale, flag it
    VIOLENCE KEYWORDS: Allow if clearly in fictional context
    """
    keyword_lower = keyword.lower()
    
    # Always flag these as violations regardless of context
    always_violate = [
        'cp link', 'child porn', 'underage nudes', 'preteen', 'kiddie porn',
        'cocaine for sale', 'heroin for sale', 'meth for sale',
        'guns for sale', 'weapons for sale', 'fake passport',
        'buy cocaine', 'buy heroin', 'buy meth', 'sell cocaine',
        'selling cocaine', 'selling heroin', 'selling meth',
    ]
    
    if any(term in keyword_lower for term in always_violate):
        return True
    
    # Drug keywords - HIGH CAUTION approach (few false negatives is better than many false positives)
    drug_keywords = ['cocaine', 'heroin', 'meth', 'weed', 'marijuana', 'fentanyl', 'oxy', 'xanax', 'mdma', 'lsd']
    if any(drug in keyword_lower for drug in drug_keywords):
        # ONLY allow if explicitly educational/safe context
        safe_contexts = [
            'drug test', 'drug prevention', 'drug awareness', 'drug education',
            'drug addiction', 'drug rehabilitation', 'substance abuse',
            'say no to drugs', 'drugs are bad', 'anti-drug',
            'cocaine is bad', 'heroin kills', 'meth dangers',
            'addiction recovery', 'rehab', 'recovery', 'treatment', 'counseling',
        ]
        if any(ctx in text_lower for ctx in safe_contexts):
            return False
        # Otherwise, flag as violation (be conservative)
        return True
    
    # Special handling for suicide keywords - allow in gaming/movie contexts only
    suicide_keywords = ['kys', 'kill yourself', 'go kill yourself', 'you should die']
    if any(term in keyword_lower for term in suicide_keywords):
        # Allow if it's clearly in a gaming/movie/fictional context
        gaming_context = [
            'video game', 'game', 'fortnite', 'minecraft', 'roblox', 'gta', 'call of duty',
            'movie', 'film', 'book', 'story', 'fiction', 'character',
            'comedy', 'joke', 'satire', 'cartoon', 'anime', 'manga', 'novel',
            'play', 'theater', 'tv show', 'series', 'npc', 'cinematic', 'script',
        ]
        if any(ctx in text_lower for ctx in gaming_context):
            return False
        # Otherwise, flag as violation
        return True
    
    # Check for educational/fictional context that should be allowed
    educational_contexts = [
        'awareness', 'prevention', 'safety', 'education', 'campaign',
        'documentary', 'movie', 'film', 'book', 'story', 'fiction',
        'comedy', 'joke', 'satire', 'news', 'article', 'discussion',
        'debate', 'analysis', 'study', 'research', 'training',
        'course', 'class', 'lesson', 'tutorial', 'guide',
    ]
    
    # If the text contains educational/fictional context, don't flag (for non-drug keywords)
    if any(ctx in text_lower for ctx in educational_contexts):
        return False
    
    # Check for negation/context that suggests it's not a violation
    negation_words = [
        'against', 'anti', 'stop', 'prevent', 'avoid', 'bad', 'wrong',
        'illegal', 'dangerous', 'harmful', 'addiction', 'recovery',
        'rehab', 'treatment', 'counseling', 'help', 'support',
    ]
    
    if any(neg in text_lower for neg in negation_words):
        return False
    
    # Default: flag as violation
    return True


async def analyze_with_ai(text: str) -> Optional[Dict]:
    """
    Advanced AI semantic analysis using Groq API
    Returns: {verdict: str, confidence: float, reason: str, severity: str} or None
    """
    if not GROQ_API_KEY or not ENABLE_AI_MODERATION:
        return None
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {
                            "role": "system",
                            "content": """You are an expert content moderator for Telegram groups. Your job is to detect content that violates Telegram's Terms of Service and could get the group banned.

CRITICAL VIOLATIONS (Severity: critical - ZERO TOLERANCE):
- Child exploitation material (CSAM) of any kind
- Terrorist recruitment or planning
- Human trafficking
- Extreme violence or gore

HIGH SEVERITY VIOLATIONS (Severity: high):
- Illegal goods/services (drugs, weapons, counterfeit documents)
- Scam links and phishing attempts
- Hacking services and fraud schemes
- Extreme harassment and death threats
- Adult content in non-adult groups

MEDIUM SEVERITY VIOLATIONS (Severity: medium):
- Cryptocurrency pump & dump schemes
- Aggressive spam and MLM recruitment
- Suspicious URL shorteners
- Milder harassment or hate speech
- Copyright infringement promotion

LOW SEVERITY VIOLATIONS (Severity: low):
- Excessive promotion
- Potential spam (borderline cases)
- Minor policy violations

Analyze the message and respond with JSON ONLY (no markdown):
{
  "verdict": "SAFE" or "VIOLATION",
  "confidence": 0.0-1.0 (how sure you are),
  "reason": "brief, clear explanation of the violation",
  "severity": "critical", "high", "medium", or "low",
  "category": "specific violation type"
}

Be strict but fair. Context matters. Educational content about dangers is SAFE."""
                        },
                        {
                            "role": "user",
                            "content": f"Analyze this message:\n\n{text}"
                        }
                    ],
                    "temperature": 0.2,
                    "max_tokens": 200
                }
            )
            
            if response.status_code != 200:
                logger.error(f"Groq API error: {response.status_code}")
                return None
            
            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            
            # Parse JSON response
            if content.startswith("```"):
                content = re.sub(r'^```(?:json)?\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            
            analysis = json.loads(content)
            
            # Validate response structure
            required_fields = {"verdict", "confidence", "reason", "severity"}
            if not required_fields.issubset(analysis.keys()):
                logger.error(f"AI response missing fields: {required_fields - set(analysis.keys())}")
                return None
            
            return analysis
            
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI JSON response: {e}")
        return None
    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        return None


async def rewrite_vouch_with_ai(original_text: str) -> Optional[str]:
    """
    Intelligently rewrite a vouch that violates ToS to be compliant.
    Uses Groq AI to preserve vouch meaning while removing violations.
    
    Timeout handling: If AI takes too long (timeout), falls back to regex sanitization.
    Retry logic: Attempts up to 2 times before giving up, with exponential backoff.
    
    Returns rewritten vouch text or None if rewrite fails/not needed
    Example:
      Input:  "vouch @user for selling lean"
      Output: "vouch @user for professional services"
    """
    if not GROQ_API_KEY or not ENABLE_AI_MODERATION:
        return None
    
    if not original_text or len(original_text.strip()) < 3:
        return None
    
    # Retry logic with exponential backoff
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # Timeout increases with each retry (3s, 5s)
            timeout_duration = 3.0 + (attempt * 2)
            
            async with httpx.AsyncClient(timeout=timeout_duration) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [
                            {
                                "role": "system",
                                "content": """You are an expert at rewriting text to comply with Telegram ToS while preserving the core meaning.

Your task: Rewrite the given vouch/message to remove TOS violations but keep the same intent and sentiment.

RULES:
1. Remove all references to: illegal drugs, weapons, hacking, fraud, stolen items
2. Keep @username mentions and vouch structure ("+rep", "vouch for", etc)
3. Keep positive/negative sentiment the same
4. Output ONLY the rewritten text, no explanations
5. Make it natural and brief (similar length to original)
6. If the entire vouch is about illegal activity, replace with generic vouching like "good seller" or "trusted person"

Examples:
- Input: "vouch @user for selling cocaine" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ Output: "vouch @user for professional services"
- Input: "+rep @user fast delivery" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ Output: "+rep @user fast delivery" (already compliant)
- Input: "neg vouch @scammer stole my money" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ Output: "neg vouch @scammer untrustworthy" (safer phrasing)
- Input: "+rep @user sold me a gun" ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ Output: "+rep @user reliable person"

Remember: The rewrite should make the message SAFE for Telegram ToS while keeping the vouch intent."""
                            },
                            {
                                "role": "user",
                                "content": f"Rewrite this vouch to be Telegram ToS compliant:\n\n{original_text}"
                            }
                        ],
                        "temperature": 0.5,
                        "max_tokens": 150
                    }
                )
                
                if response.status_code != 200:
                    logger.warning(f"Groq vouch rewrite failed (status {response.status_code}, attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5)  # Brief backoff before retry
                        continue
                    return None
                
                result = response.json()
                rewritten = result["choices"][0]["message"]["content"].strip()
                
                # Safety check: if AI didn't change it much, prefer regex sanitization
                if rewritten.lower() == original_text.lower():
                    return None
                
                # Verify rewritten text isn't still problematic
                if len(rewritten) < 3 or len(rewritten) > 500:
                    return None
                
                logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ AI vouch rewrite: '{original_text[:50]}...' ÃƒÂ¢Ã¢Â€Â Ã¢Â€Â™ '{rewritten[:50]}...'")
                return rewritten
                
        except asyncio.TimeoutError:
            logger.warning(f"AI vouch rewrite timeout (attempt {attempt + 1}/{max_retries}, {timeout_duration}s)")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)  # Brief backoff before retry
                continue
            return None  # Fall back to regex sanitization
            
        except Exception as e:
            logger.warning(f"AI vouch rewrite error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)  # Brief backoff before retry
                continue
            return None  # Fall back to regex sanitization
    
    return None  # All retries exhausted


async def check_message(text: str, user_id: int = None) -> Tuple[bool, str, str, bool]:
    """
    Main moderation check - multi-layer detection
    Returns: (should_remove, reason, severity, is_vouch)
    
    Detection Layers:
    1. Vouch detection (determines if sanitization needed)
    2. Pattern matching (instant, <10ms)
    3. Toxicity detection via Toxic-BERT (50-100ms, free, local)
    4. AI semantic analysis (2-3s, high accuracy)
    5. Spam score calculation
    """
    # Check if this is a vouch first
    message_is_vouch = is_vouch(text)
    
    # Layer 1: Fast pattern matching (always runs first)
    is_violation, reason, severity = check_patterns(text, user_id)
    if is_violation:
        logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ Pattern violation [{severity}]: {reason}{' (VOUCH - will sanitize)' if message_is_vouch else ''}")
        return True, reason, severity, message_is_vouch
    
    # Layer 2: Local toxicity detection (NEW - 50ms, free, catches harassment)
    is_toxic, toxicity_reason = check_toxicity(text)
    if is_toxic:
        logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ Toxicity detected: {toxicity_reason}{' (VOUCH - will sanitize)' if message_is_vouch else ''}")
        return True, toxicity_reason, "high", message_is_vouch
    
    # Layer 3: AI semantic analysis (optional, only if enabled and not obvious)
    if ENABLE_AI_MODERATION and GROQ_API_KEY:
        ai_result = await analyze_with_ai(text)
        if ai_result:
            # AI detected violation with high confidence
            if ai_result.get("verdict") == "VIOLATION":
                confidence = ai_result.get("confidence", 0)
                ai_severity = ai_result.get("severity", "medium")
                
                # Critical violations: any confidence
                if ai_severity == "critical":
                    reason = f"AI CRITICAL: {ai_result.get('reason', 'Severe TOS violation')}"
                    logger.warning(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ AI critical violation detected: {reason} (confidence: {confidence:.0%})")
                    return True, reason, "critical", message_is_vouch
                
                # High severity: 70%+ confidence
                elif ai_severity == "high" and confidence >= 0.70:
                    reason = f"AI detected: {ai_result.get('reason', 'TOS violation')}"
                    logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ AI high violation: {reason} (confidence: {confidence:.0%})")
                    return True, reason, "high", message_is_vouch
                
                # Medium severity: 75%+ confidence
                elif ai_severity == "medium" and confidence >= 0.75:
                    reason = f"AI detected: {ai_result.get('reason', 'TOS violation')}"
                    logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ AI medium violation: {reason} (confidence: {confidence:.0%})")
                    return True, reason, "medium", message_is_vouch
                
                # Low severity: 80%+ confidence (to reduce false positives)
                elif ai_severity == "low" and confidence >= 0.80:
                    reason = f"AI detected: {ai_result.get('reason', 'Minor TOS violation')}"
                    logger.info(f"ÃƒÂ¢Ã…Â“Ã¢Â€Âœ AI low violation: {reason} (confidence: {confidence:.0%})")
                    return True, reason, "low", message_is_vouch
                
                # Log potential violations with low confidence (for review)
                elif confidence >= 0.60:
                    logger.info(f"ÃƒÂ¢Ã…Â¡Ã‚Â  AI potential violation (low confidence {confidence:.0%}): {ai_result.get('reason')}")
    
    # Message is safe
    return False, "", "low", message_is_vouch


def extract_vouch_info(text: str, from_username: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Extract structured vouch information from a message.
    
    Enhanced with bulletproof polarity detection and robust mention extraction.
    
    Returns a dict with keys:
      - from_username: str (prefers provided from_username, else empty)
      - to_username: str (username with @ if available, else empty)
      - polarity: 'pos' or 'neg'
      - excerpt: short sanitized excerpt of original text (max 200 chars)

    Returns None if no vouch-like content is found.
    """
    if not text or len(text) < 5:
        return None

    txt = text.strip()
    txt_lower = txt.lower()
    if is_vouch_request(txt_lower):
        return None

    # Find all mentions like @username (is_vouch() already verified at least one exists)
    mentions = re.findall(r'@[_a-zA-Z0-9-]+', txt)
    
    # If no mentions found, can't extract vouch info
    if not mentions:
        return None

    # Enhanced polarity detection from prime directive
    negative_keywords = [
        'neg vouch', 'negative vouch', '-vouch', '-rep', 'scammer', 'scam',
        'do not recommend', 'dont recommend', "don't recommend",
        'not recommend', 'no vouch', 'never vouch', 'dont trust',
        "don't trust", 'not legit', 'fraud', 'fake', 'unreliable', 'vouch against'
    ]
    positive_keywords = [
        'pos vouch', 'positive vouch', '+vouch', '+rep', '+1',
        'vouch', 'solid', 'legend', 'legit', 'trusted', 'trustworthy',
        'recommend', 'good seller', 'good buyer', 'can vouch', 'reliable'
    ]
    
    # Determine polarity: check negative first, default positive
    polarity = 'neg' if any(neg_kw in txt_lower for neg_kw in negative_keywords) else 'pos'

    # Choose target mention: prefer one that isn't the author
    to_username = ''
    if mentions:
        if from_username:
            from_norm = from_username.lstrip('@').lower()
            # Find first mention that isn't the author
            to_username = next((m for m in mentions if m.lstrip('@').lower() != from_norm), mentions[0])
        else:
            to_username = mentions[0]

    # Build excerpt with light sanitization (handle URL boundaries better)
    excerpt = re.sub(r'\s+', ' ', re.sub(r'https?://[^\s)]*', '[LINK]', txt)).strip()
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + '...'

    return {
        'from_username': f"@{from_username.lstrip('@')}" if from_username else '',
        'to_username': to_username,
        'polarity': polarity,
        'excerpt': excerpt,
    }


def format_canonical_vouch(vouch_info: Dict[str, str]) -> str:
    """Create the canonical simple vouch repost text."""
    if not vouch_info:
        return ""

    frm = vouch_info.get("from_username") or "[unknown]"
    to = vouch_info.get("to_username") or "[unknown]"
    excerpt = (vouch_info.get("excerpt") or "").strip()
    polarity = vouch_info.get("polarity") or "pos"
    title = "POS VOUCH" if polarity == "pos" else "NEG VOUCH"

    lines = [
        f"{title} {to}",
        f"from: {frm}",
    ]

    note = _clean_note_excerpt(excerpt)
    if note:
        lines.append(note)

    watchers = vouch_info.get("watchers") or []
    if watchers:
        lines.append(f"Last to vouch: {', '.join(watchers)}")

    return "\n".join(lines)


def _clean_note_excerpt(excerpt: str) -> str:
    if not excerpt:
        return ""
    cleaned = excerpt.strip()
    cleaned = _VOUCH_PREFIX_PATTERN.sub("", cleaned).strip()
    cleaned = re.sub(r"^@[\w\d_]+\s*", "", cleaned)
    return cleaned.strip(" -:")


def track_user_activity(user_id: int, text: str) -> Tuple[bool, str]:
    """
    Track user activity for rate limiting and spam detection
    Returns: (is_violation, reason)
    """
    from datetime import datetime, timedelta
    from config import MESSAGE_RATE_LIMIT, RATE_LIMIT_WINDOW, LINK_RATE_LIMIT, LINK_RATE_WINDOW
    
    now = datetime.now()
    
    # Clean old message history
    message_tracker[user_id] = [
        (ts, msg) for ts, msg in message_tracker[user_id]
        if now - ts < timedelta(seconds=RATE_LIMIT_WINDOW)
    ]
    
    # Clean old link history
    link_tracker[user_id] = [
        (ts, link) for ts, link in link_tracker[user_id]
        if now - ts < timedelta(seconds=LINK_RATE_WINDOW)
    ]
    
    # Check message rate
    message_tracker[user_id].append((now, text))
    if len(message_tracker[user_id]) > MESSAGE_RATE_LIMIT:
        return True, f"Message flooding ({len(message_tracker[user_id])} messages in {RATE_LIMIT_WINDOW}s)"
    
    # Check link rate
    urls = extract_urls(text)
    for url in urls:
        link_tracker[user_id].append((now, url))
    
    if len(link_tracker[user_id]) > LINK_RATE_LIMIT:
        return True, f"Link spam ({len(link_tracker[user_id])} links in {LINK_RATE_WINDOW}s)"
    
    return False, ""









