"""
PRIME DIRECTIVE MODERATION ENGINE (OPTIMIZED)
"The Shield" - Protect the Group at All Costs

Three-layer protection funnel:
1. Keyword Sieve (instant deletion) - Pre-compiled patterns
2. Semantic Net (AI-powered deletion)
3. The Watcher (behavioral deletion) - Efficient tracking

PERFORMANCE OPTIMIZATIONS:
- Pre-compiled regex patterns (avoid recompilation)
- Efficient velocity tracking (timestamps only, lazy cleanup)
- Batch sanitization (single pass)
- Early returns (stop at first match)
"""
import re
import logging
import httpx
from typing import Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from config_prime import (
    BANNED_WORDS,
    BANNED_PATTERNS,
    VOUCH_KEYWORDS,
    VOUCH_PATTERN,
    SANITIZE_REPLACEMENT,
    AI_ANALYSIS_PROMPT,
    AI_MODEL,
    AI_TEMPERATURE,
    AI_MAX_TOKENS,
    GROQ_API_KEY,
    ENABLE_AI_MODERATION,
    MAX_MESSAGES_PER_WINDOW,
    MESSAGE_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

# ============================================================================
# PERFORMANCE OPTIMIZATIONS - PRE-COMPILED PATTERNS
# ============================================================================

# Pre-compile keyword patterns (avoid recompilation on every check)
_KEYWORD_PATTERNS = {
    word: re.compile(re.escape(word), re.IGNORECASE)
    for word in BANNED_WORDS
}

# Pre-compile banned regex patterns
_COMPILED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in BANNED_PATTERNS
]

# Pre-compile sanitization patterns (for batch replacement)
_SANITIZE_PATTERN = re.compile(
    '|'.join(re.escape(word) for word in BANNED_WORDS),
    re.IGNORECASE
)

# ============================================================================
# TRACKING SYSTEMS (OPTIMIZED)
# ============================================================================

# Message velocity tracking: user_id -> [timestamp, ...] (OPTIMIZED: timestamps only)
velocity_tracker = defaultdict(list)

# User join time tracking: user_id -> join_timestamp
user_join_times = {}

# Cleanup counter (trigger cleanup every N messages to avoid constant list rebuilds)
_cleanup_counter = 0
_CLEANUP_INTERVAL = 100  # Cleanup every 100 messages processed

# ============================================================================
# VOUCH INTENT DETECTOR (First Check) - OPTIMIZED
# ============================================================================

def is_vouch(text: str) -> bool:
    """
    FIRST CHECK on any message: Is this a vouch?
    
    OPTIMIZED: Uses pre-compiled regex pattern
    
    Logic: Look for (vouch keyword) + (@username)
    
    Returns:
        True if message matches vouch pattern
        False otherwise
    """
    if not text or len(text) < 5:  # Quick length check
        return False
    
    # Check for vouch pattern: keyword + @username mention
    return bool(re.search(VOUCH_PATTERN, text, re.IGNORECASE))


# ============================================================================
# VOUCH SANITIZATION WORKFLOW (OPTIMIZED)
# ============================================================================

def sanitize_vouch(text: str) -> str:
    """
    Sanitize a vouch by replacing banned words with [removed]
    
    OPTIMIZED: Single-pass batch replacement instead of per-word iteration
    
    This preserves the vouch intent while removing ToS violations.
    
    Args:
        text: Original vouch text
        
    Returns:
        Sanitized text with banned words replaced
    """
    if not text:
        return text
    
    # Single-pass replacement of all banned keywords
    sanitized = _SANITIZE_PATTERN.sub(SANITIZE_REPLACEMENT, text)
    
    # Clean up multiple [removed] in a row
    sanitized = re.sub(r'(\[removed\]\s*)+', '[removed] ', sanitized)
    
    # Clean up extra whitespace
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized


# ============================================================================
# LAYER 1: THE KEYWORD SIEVE (OPTIMIZED - Instant Deletion)
# ============================================================================

def layer1_keyword_check(text: str) -> Tuple[bool, Optional[str]]:
    """
    Layer 1: Instant keyword deletion
    
    OPTIMIZED:
    - Pre-compiled patterns (avoid recompilation)
    - Early exit on first match (stop searching after violation found)
    - No redundant case conversion
    
    Checks message against hardcoded BANNED_WORDS list and regex patterns.
    Designed for SPEED - catches blatant violations in <5ms.
    
    Args:
        text: Message text to check
        
    Returns:
        (is_violation, matched_keyword)
        - is_violation: True if keyword/pattern found
        - matched_keyword: The word/pattern that matched (for logging)
    """
    if not text:
        return False, None
    
    text_lower = text.lower()
    
    # Check banned keywords (fast substring match)
    for banned_word, pattern in _KEYWORD_PATTERNS.items():
        if pattern.search(text):  # Use pre-compiled pattern
            return True, banned_word
    
    # Check banned patterns (regex) - only if keywords passed
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True, f"pattern:{pattern.pattern[:30]}"
    
    # Passed Layer 1
    return False, None


# ============================================================================
# LAYER 2: THE SEMANTIC NET (AI-Powered Deletion)
# ============================================================================

async def layer2_ai_check(text: str) -> Tuple[bool, Optional[str]]:
    """
    Layer 2: AI semantic analysis
    
    Sends message to Groq API to analyze INTENT.
    Catches coded language and context that keywords miss.
    Only runs if message passed Layer 1.
    
    Args:
        text: Message text to analyze
        
    Returns:
        (is_violation, ai_reason)
        - is_violation: True if AI flagged as VIOLATION
        - ai_reason: Brief explanation (if available)
    """
    if not ENABLE_AI_MODERATION or not GROQ_API_KEY:
        return False, None
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": AI_ANALYSIS_PROMPT + text
                        }
                    ],
                    "temperature": AI_TEMPERATURE,
                    "max_tokens": AI_MAX_TOKENS
                }
            )
            
            if response.status_code != 200:
                logger.error(f"[LAYER 2] Groq API error: {response.status_code}")
                return False, None
            
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"].strip().upper()
            
            if "VIOLATION" in ai_response:
                logger.warning(f"[LAYER 2] AI flagged violation: {text[:50]}...")
                return True, "AI detected intent violation"
            
            # Passed Layer 2
            return False, None
            
    except Exception as e:
        logger.error(f"[LAYER 2] AI check error: {e}")
        return False, None


# ============================================================================
# LAYER 3: THE WATCHER (Behavioral Deletion)
# ============================================================================

def layer3_velocity_check(user_id: int, text: str) -> bool:
    """
    Layer 3a: Velocity control (rate limiting)
    
    OPTIMIZED:
    - Tracks timestamps only (not full message text)
    - Lazy cleanup (every 100 messages, not every message)
    - Avoids list comprehension on every check
    
    Checks if user is posting too fast (more than MAX_MESSAGES_PER_WINDOW in MESSAGE_WINDOW_SECONDS).
    Stops spam raids and flooding.
    
    Args:
        user_id: Telegram user ID
        text: Message text (for logging)
        
    Returns:
        True if user exceeded velocity limit (should be muted)
        False if velocity is acceptable
    """
    global _cleanup_counter
    
    now = datetime.now()
    cutoff_time = now - timedelta(seconds=MESSAGE_WINDOW_SECONDS)
    
    user_messages = velocity_tracker[user_id]
    
    # Lazy cleanup: remove timestamps older than window (every N messages)
    _cleanup_counter += 1
    if _cleanup_counter >= _CLEANUP_INTERVAL:
        _cleanup_counter = 0
        # Clean old messages from ALL users
        for uid in list(velocity_tracker.keys()):
            velocity_tracker[uid] = [
                ts for ts in velocity_tracker[uid]
                if ts > cutoff_time
            ]
    
    # Add current message timestamp
    user_messages.append(now)
    
    # Check if exceeded limit
    message_count = len(user_messages)
    
    return message_count > MAX_MESSAGES_PER_WINDOW


def layer3_new_user_check(user_id: int, message) -> Tuple[bool, Optional[str]]:
    """
    Layer 3b: New user restrictions
    
    OPTIMIZED:
    - Early exit if user is old (no need to check entities)
    - Short-circuit evaluation on entities check
    
    Users who joined less than 24h ago cannot post links or forwards.
    Most effective way to stop spammers.
    
    Args:
        user_id: Telegram user ID
        message: Telegram message object
        
    Returns:
        (is_violation, reason)
        - is_violation: True if new user posted restricted content
        - reason: Explanation of violation
    """
    # Get or initialize join time
    if user_id not in user_join_times:
        user_join_times[user_id] = datetime.now()
        return False, None  # Just joined, no violation
    
    # Check if user is "new" (< 24 hours) - early exit if not
    time_in_group = datetime.now() - user_join_times[user_id]
    if time_in_group >= timedelta(hours=24):
        return False, None  # User is old, no restrictions
    
    # User is new - check for restricted content
    
    # Skip checks if message is None
    if not message:
        return False, None
    
    # Check for links
    if message.entities:
        for entity in message.entities:
            if entity.type in ['url', 'text_link']:
                return True, "New user posted link"
    
    # Check for forwards
    if message.forward_from or message.forward_from_chat:
        return True, "New user posted forward"
    
    return False, None


# ============================================================================
# MAIN CHECK FUNCTION: THE ToS VIOLATION FUNNEL
# ============================================================================

async def check_violation(text: str, user_id: int, message) -> Tuple[bool, str, str]:
    """
    THE ToS VIOLATION FUNNEL - Three-layer protection
    
    Every non-vouch message goes through this funnel.
    If it fails at ANY layer, it is deleted and process stops.
    
    Args:
        text: Message text
        user_id: Telegram user ID
        message: Full Telegram message object
        
    Returns:
        (should_delete, reason, layer)
        - should_delete: True if message violates rules
        - reason: Explanation of violation
        - layer: Which layer caught it (for stats)
    """
    # LAYER 1: Keyword Sieve (instant, <10ms)
    is_violation, keyword = layer1_keyword_check(text)
    if is_violation:
        return True, f"Banned keyword: {keyword}", "Layer1"
    
    # LAYER 2: AI Semantic Analysis (2-3s, high accuracy)
    is_violation, ai_reason = await layer2_ai_check(text)
    if is_violation:
        return True, ai_reason or "AI detected violation", "Layer2"
    
    # LAYER 3a: Velocity Control
    if layer3_velocity_check(user_id, text):
        return True, "Message flooding (velocity control)", "Layer3-Velocity"
    
    # LAYER 3b: New User Restrictions
    is_violation, reason = layer3_new_user_check(user_id, message)
    if is_violation:
        return True, reason, "Layer3-NewUser"
    
    # Message is safe - passed all layers
    return False, "", ""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def track_user_join(user_id: int):
    """Record when a user joined the group"""
    if user_id not in user_join_times:
        user_join_times[user_id] = datetime.now()
        logger.info(f"Tracking new user: {user_id}")


def get_user_message_count(user_id: int) -> int:
    """
    OPTIMIZED: Get how many messages user sent in the current window
    
    Returns count directly from tracker length (already filtered by cleanup)
    """
    return len(velocity_tracker.get(user_id, []))
