from __future__ import annotations

from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from config import MAX_STRIKES
from modbot.engine.orchestrator import analyze_message
from modbot.services.metrics import stats, touch_group
from modbot.services.strikes import record_violation
from modbot.services.vouches import handle_clean_vouch, handle_dirty_vouch
from moderation import track_user_activity


_processed_messages = {}
_MESSAGE_DEDUP_WINDOW = 300  # seconds


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    # Deduplication window
    now = datetime.now().timestamp()
    key = (message.chat_id, message.message_id)
    # Clean old entries
    for k, ts in list(_processed_messages.items()):
        if now - ts > _MESSAGE_DEDUP_WINDOW:
            _processed_messages.pop(k, None)
    if key in _processed_messages:
        return
    _processed_messages[key] = now

    # Track group
    touch_group(message.chat_id)

    # Rate limiting first
    is_flood, flood_reason = track_user_activity(update.effective_user.id, message.text)
    if is_flood:
        try:
            await message.delete()
        except Exception:
            pass
        stats["total_removed"] += 1
        stats["last_24h"] += 1
        stats["violations"][flood_reason] += 1
        stats["severity_counts"]["medium"] += 1
        stats["users_warned"] += 1
        return

    # Content analysis
    decision = await analyze_message(message.text, update.effective_user.id)

    if decision.is_vouch and not decision.should_remove:
        await handle_clean_vouch(message, update.effective_user.username)
        return

    if decision.should_remove:
        if decision.is_vouch:
            await handle_dirty_vouch(message, decision.reason)
            stats["total_removed"] += 1
            stats["last_24h"] += 1
            stats["violations"]["Sanitized vouch"] += 1
            stats["severity_counts"][decision.severity] += 1
            stats["vouches_sanitized"] += 1
            return

        # Non-vouch violation
        try:
            await message.delete()
        except Exception:
            pass

        current = record_violation(update.effective_user.id, decision.reason, decision.severity)
        stats["total_removed"] += 1
        stats["last_24h"] += 1
        stats["violations"][decision.reason] += 1
        stats["severity_counts"][decision.severity] += 1
        stats["users_warned"] += 1

