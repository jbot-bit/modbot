from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple, List
from telegram import Message, Chat, User
from telegram import MessageEntity
from datetime import datetime

logger = logging.getLogger(__name__)

from moderation import (
    extract_vouch_info,
    format_canonical_vouch,
    rewrite_vouch_with_ai,
    extract_mentions,
    sanitize_text,
)
from modbot.engine.orchestrator import analyze_message
from modbot.services.metrics import stats
from vouch_db import (
    store_vouch,
    search_vouches,
    get_vouch_stats,
    format_vouch_for_display,
    update_vouch_message_id,
    check_vouch_duplicate_24h,
    get_prior_vouchers_for_target,
)

from asyncio import Lock

# Create a lock for database operations
_db_lock = Lock()

async def store_vouch_with_lock(*args, **kwargs):
    """Wrapper to ensure vouch storage is thread-safe."""
    async with _db_lock:
        store_vouch(*args, **kwargs)


async def handle_clean_vouch(message: Message, from_username: Optional[str]) -> None:
    """
    Handle a vouch that passed moderation checks.
    Posts the canonical vouch and stores it in the database.
    """
    vinfo = extract_vouch_info(message.text or "", from_username=from_username)
    if not vinfo:
        logger.warning(f"Could not extract vouch info from: {message.text}")
        return
    
    targets = _collect_target_usernames(message.text or "", from_username)
    if not targets:
        logger.warning(f"No valid targets found in vouch: {message.text}")
        return
    
    logger.info(f"VOUCH HANDLER: Extracted {len(targets)} target(s): {targets}")

    polarity = vinfo.get("polarity", "pos")
    canonical_entries: List[str] = []
    target_entries: List[Tuple[str, str]] = []

    for target in targets:
        # Skip if user already vouched for this target in the last 24h
        if check_vouch_duplicate_24h(
            from_user_id=message.from_user.id,
            to_username=target,
            polarity=polarity,
        ):
            logger.info(f"Duplicate vouch detected for user {message.from_user.id} -> @{target}")
            continue

        vinfo_target = dict(vinfo)
        vinfo_target["to_username"] = f"@{target}"
        if polarity == "neg":
            watchers = _format_prior_watchers(target)
            if watchers:
                vinfo_target["watchers"] = watchers
        canonical_text = format_canonical_vouch(vinfo_target)

        canonical_entries.append(canonical_text)
        target_entries.append((target, canonical_text))

    if not target_entries:
        # Nothing to store (all were duplicates within 24h). Leave the
        # original message posted so users can keep their own vouches.
        await _send_temp_ack(
            message.chat,
            "[INFO] Already vouched within the last 24h.",
        )
        return

    # Leave the original message posted. Store each vouch in the DB using
    # the original message id so it can be referenced/searchable later.
    # Capture user ids from any text_mention entities present on the message
    entity_user_map = _collect_target_user_ids_from_entities(message)

    for target, canonical_text in target_entries:
        logger.info(f"Storing vouch for @{target} from {from_username or message.from_user.username}")
        logger.debug(f"Original text: {message.text}")
        await store_vouch_with_lock(
            from_user_id=message.from_user.id,
            from_username=(from_username or ""),
            from_display_name=message.from_user.first_name,
            to_user_id=entity_user_map.get(target),
            to_username=target,
            to_display_name=None,
            polarity=polarity,
            original_text=message.text or "",
            canonical_text=canonical_text,
            chat_id=message.chat_id,
            message_id=message.message_id,
            is_sanitized=False,
        )
        logger.debug("Vouch stored for target %s, message=%s", target, message.message_id)

    await _send_temp_ack(
        message.chat,
        "[OK] Thank you. Vouch logged.",
        reply_to=message.message_id,
    )


# Ensure retry logic is enforced before reposting
async def handle_dirty_vouch(message: Message, reason: str) -> None:
    """
    Handle vouches that contain ToS violations by deleting the message and notifying the user.

    Args:
        message: The vouch message with ToS violations.
        reason: The violation reason detected.
    """
    original_text = message.text or ""

    # Delete the original message
    try:
        await message.delete()
    except Exception as e:
        logger.debug(f"Failed to delete message: {e}")
        return

    # Notify the user with the violation reason and admin contact
    warning_msg = (
        f"⚠️ **Vouch Rejected - {reason}**\n\n"
        "Your vouch was deleted because it violated our community guidelines.\n\n"
        "💡 **Tip:** Please review the guidelines and rephrase your vouch.\n\n"
        "If you have any questions, contact @admin."
    )

    await _send_temp_ack(message.chat, warning_msg, delay=15)
    logger.info(f"Vouch deleted for user {message.from_user.id} due to: {reason}")


async def submit_vouch_via_command(
    chat: Chat,
    user: User,
    args_text: str,
    polarity: str,
    reply_to_message_id: Optional[int] = None,
    decision_reason: str = "",
) -> Tuple[bool, str]:
    """
    Used by /vouch and /neg commands to quickly post a compliant vouch.
    Returns (success, detail_message).
    """
    args_text = (args_text or "").strip()
    if not args_text:
        return False, "Please include the @username you are vouching for."

    prefix = "+vouch" if polarity == "pos" else "neg vouch"
    raw_text = f"{prefix} {args_text}".strip()

    decision = await analyze_message(raw_text, user.id)
    if not decision.is_vouch:
        return False, "Include at least one @username so the bot knows who you're vouching for."

    vinfo = extract_vouch_info(raw_text, from_username=user.username)
    targets = _collect_target_usernames(raw_text, user.username)
    if not vinfo or not targets:
        return False, "Could not find a target @username. Example: `/vouch @user great courier`"
    vinfo["polarity"] = polarity

    is_sanitized = False
    needs_sanitize = decision.should_remove
    note_excerpt = args_text

    if needs_sanitize:
        rewritten = await rewrite_vouch_with_ai(raw_text)
        sanitized_content = rewritten or sanitize_text(raw_text)
        note_excerpt = sanitized_content.replace("\n", " ").strip()
        is_sanitized = True

    if len(note_excerpt) > 160:
        note_excerpt = note_excerpt[:157] + "..."

    send_kwargs = {"reply_to_message_id": reply_to_message_id} if reply_to_message_id else {}

    canonical_entries: List[str] = []
    stored_targets: List[Tuple[str, str]] = []

    from_username = f"@{user.username}" if user.username else user.full_name

    for target in targets:
        if check_vouch_duplicate_24h(user.id, target, polarity):
            continue
        entry_info = {
            "from_username": from_username,
            "to_username": f"@{target}",
            "polarity": polarity,
            "excerpt": note_excerpt,
        }
        if polarity == "neg":
            watchers = _format_prior_watchers(target)
            if watchers:
                entry_info["watchers"] = watchers
        entry = format_canonical_vouch(entry_info)
        canonical_entries.append(entry)
        stored_targets.append((target, entry))

    if not stored_targets:
        return False, "Looks like you already vouched for that user in the last 24 hours."

    message_text = "\n\n".join(canonical_entries)

    try:
        sent = await chat.send_message(message_text, **send_kwargs)
    except Exception:
        return False, "Failed to post the vouch. Try again in a moment."

    for target, canonical_entry in stored_targets:
        await store_vouch_with_lock(
            from_user_id=user.id,
            from_username=user.username or "",
            from_display_name=user.first_name,
            to_user_id=None,
            to_username=target,
            to_display_name=None,
            polarity=polarity,
            original_text=raw_text,
            canonical_text=canonical_entry,
            chat_id=chat.id,
            message_id=sent.message_id,
            is_sanitized=is_sanitized,
        )
    ack_text = (
        "✅ Thank you. Vouch logged and ToS compliant."
        if is_sanitized
        else "✅ Thank you. Vouch logged and printed."
    )
    await _send_temp_ack(chat, ack_text, reply_to=sent.message_id)

    if is_sanitized:
        stats["vouches_sanitized"] += 1
        return True, ""
    return True, ""


def _collect_target_usernames(text: str, from_username: Optional[str]) -> List[str]:
    mentions = extract_mentions(text)
    if not mentions:
        return []
    seen = set()
    from_norm = (from_username or "").lstrip("@").lower()
    results: List[str] = []
    for mention in mentions:
        norm = mention.lower().lstrip("@")
        if norm == from_norm or norm in seen:
            continue
        seen.add(norm)
        # store normalized, lower-case usernames (no @)
        results.append(norm)
    return results


def _collect_target_user_ids_from_entities(message: Message) -> dict:
    """Return a mapping username_lower -> user.id for text_mention entities on the message.

    This helps when a vouch mentions someone via an actual Telegram user mention
    (MessageEntity type "text_mention"), because that includes the target user id.
    """
    mapping = {}
    if not message or not getattr(message, "entities", None):
        return mapping

    for ent in message.entities:
        try:
            if ent.type == MessageEntity.TEXT_MENTION and getattr(ent, "user", None):
                # Extract the exact mention text from the message and normalize
                text = (message.text or "")
                mention_text = text[ent.offset : ent.offset + ent.length]
                if mention_text:
                    norm = mention_text.lstrip("@").lower()
                    mapping[norm] = ent.user.id
        except Exception:
            continue

    return mapping


async def _send_temp_ack(chat: Chat, text: str, reply_to: Optional[int] = None, delay: int = 10) -> None:
    try:
        sent = await chat.send_message(
            text,
            reply_to_message_id=reply_to,
            allow_sending_without_reply=True,
        )
    except Exception:
        return
    asyncio.create_task(_delete_message_later(sent, delay))


async def _delete_message_later(message: Message, delay: int) -> None:
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass


def _format_prior_watchers(target_username: str) -> List[str]:
    watchers = get_prior_vouchers_for_target(target_username, polarity="pos")
    if not watchers:
        return []
    formatted: List[str] = []
    seen = set()
    for watcher in watchers:
        username = watcher.get("from_username")
        if username:
            tag = f"@{username}"
        elif watcher.get("from_display_name"):
            tag = watcher["from_display_name"]
        else:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        formatted.append(tag)
        if len(formatted) >= 5:
            break
    return formatted
