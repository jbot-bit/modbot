from __future__ import annotations

import asyncio
from typing import Optional, Tuple, List
from telegram import Message, Chat, User

from moderation import (
    sanitize_text,
    extract_vouch_info,
    format_canonical_vouch,
    rewrite_vouch_with_ai,
    extract_mentions,
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


async def handle_clean_vouch(message: Message, from_username: Optional[str]) -> None:
    vinfo = extract_vouch_info(message.text or "", from_username=from_username)
    if not vinfo:
        return
    targets = _collect_target_usernames(message.text or "", from_username)
    if not targets:
        return

    polarity = vinfo.get("polarity", "pos")
    canonical_entries: List[str] = []
    target_entries: List[Tuple[str, str]] = []

    for target in targets:
        if check_vouch_duplicate_24h(
            from_user_id=message.from_user.id,
            to_username=target,
            polarity=polarity,
        ):
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
        try:
            await message.delete()
        except Exception:
            pass
        await _send_temp_ack(
            message.chat,
            "[INFO] Already vouched within the last 24h.",
        )
        return

    try:
        await message.delete()
    except Exception:
        pass

    sent = await message.chat.send_message("\n\n".join(canonical_entries))

    for target, canonical_text in target_entries:
        store_vouch(
            from_user_id=message.from_user.id,
            from_username=(from_username or ""),
            from_display_name=message.from_user.first_name,
            to_user_id=None,
            to_username=target,
            to_display_name=None,
            polarity=polarity,
            original_text=message.text or "",
            canonical_text=canonical_text,
            chat_id=message.chat_id,
            message_id=sent.message_id,
            is_sanitized=False,
        )

    await _send_temp_ack(
        message.chat,
        "[OK] Thank you. Vouch logged and printed.",
        reply_to=sent.message_id,
    )


async def handle_dirty_vouch(message: Message, reason: str) -> None:
    original_text = message.text or ""
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    vinfo = extract_vouch_info(original_text, from_username=message.from_user.username)
    polarity = (vinfo or {}).get("polarity", "pos")

    if not _should_sanitize_reason(reason):
        await handle_clean_vouch(message, message.from_user.username)
        return

    rewritten = await rewrite_vouch_with_ai(original_text)
    if rewritten:
        vouch_content = rewritten
    else:
        vouch_content = sanitize_text(original_text)

    targets = _collect_target_usernames(original_text, message.from_user.username)
    if not targets:
        targets = [message.from_user.username or ""]

    valid_targets: List[str] = []
    for target in targets:
        if check_vouch_duplicate_24h(
            from_user_id=message.from_user.id,
            to_username=target,
            polarity=polarity,
        ):
            continue
        valid_targets.append(target)

    if not valid_targets:
        try:
            await message.delete()
        except Exception:
            pass
        await _send_temp_ack(
            message.chat,
            "[INFO] Already vouched within the last 24h.",
        )
        return

    note_excerpt = vouch_content.replace("\n", " ").strip()
    if len(note_excerpt) > 160:
        note_excerpt = note_excerpt[:157] + "..."

    canonical_entries: List[str] = []
    target_entry_pairs: List[Tuple[str, str]] = []
    for target in valid_targets:
        entry_info = {
            "from_username": username,
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
        target_entry_pairs.append((target, entry))

    vouch_message = "\n\n".join(canonical_entries)

    try:
        await message.delete()
    except Exception:
        pass
    try:
        sent = await message.chat.send_message(vouch_message)
        update_vouch_message_id(message.chat_id, sent.message_id)
    except Exception:
        return

    for target, canonical_text in target_entry_pairs:
        store_vouch(
            from_user_id=message.from_user.id,
            from_username=message.from_user.username,
            from_display_name=message.from_user.first_name,
            to_user_id=None,
            to_username=target,
            to_display_name=None,
            polarity=polarity,
            original_text=original_text,
            canonical_text=canonical_text,
            chat_id=message.chat_id,
            message_id=sent.message_id,
            is_sanitized=True,
        )
    stats["vouches_sanitized"] += 1
    await _send_temp_ack(
        message.chat,
        "[OK] Thank you. Vouch logged and ToS compliant.",
        reply_to=sent.message_id,
    )


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
    needs_sanitize = decision.should_remove and _should_sanitize_reason(decision_reason)
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
        store_vouch(
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
        norm = mention.lower()
        if norm == from_norm or norm in seen:
            continue
        seen.add(norm)
        results.append(mention)
    return results


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


def _should_sanitize_reason(reason: str) -> bool:
    if not reason:
        return False
    reason_lower = reason.lower()
    return any(keyword in reason_lower for keyword in _SANITIZE_REASON_KEYWORDS)

_SANITIZE_REASON_KEYWORDS = [
    "prohibited",
    "illegal",
    "scam",
    "suspicious",
    "toxicity",
    "critical",
    "ai ",
]
