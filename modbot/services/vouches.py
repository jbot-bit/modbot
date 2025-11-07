from __future__ import annotations

from typing import Optional, Tuple
from telegram import Message, Chat, User

from moderation import (
    sanitize_text,
    extract_vouch_info,
    format_canonical_vouch,
    rewrite_vouch_with_ai,
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
)


async def handle_clean_vouch(message: Message, from_username: Optional[str]) -> None:
    vinfo = extract_vouch_info(message.text or "", from_username=from_username)
    if not vinfo:
        return

    # Prevent duplicate vouch by same person to same target in 24h
    is_dup = check_vouch_duplicate_24h(
        from_user_id=message.from_user.id,
        to_username=vinfo.get("to_username", "").lstrip("@") or None,
        polarity=vinfo.get("polarity", "pos"),
    )
    if is_dup:
        try:
            await message.reply_text("Vouch acknowledged (already vouched within 24h)")
        except Exception:
            pass
        return

    canonical_text = format_canonical_vouch(vinfo)
    store_vouch(
        from_user_id=message.from_user.id,
        from_username=(from_username or ""),
        from_display_name=message.from_user.first_name,
        to_user_id=None,
        to_username=vinfo.get("to_username", "").lstrip("@") or None,
        to_display_name=None,
        polarity=vinfo.get("polarity", "pos"),
        original_text=message.text or "",
        canonical_text=canonical_text,
        chat_id=message.chat_id,
        message_id=message.message_id,
        is_sanitized=False,
    )

    # Optionally echo canonical form if it differs
    if canonical_text and canonical_text not in (message.text or "") and not message.from_user.is_bot:
        try:
            await message.reply_text(canonical_text)
        except Exception:
            pass


async def handle_dirty_vouch(message: Message, reason: str) -> None:
    original_text = message.text or ""
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    rewritten = await rewrite_vouch_with_ai(original_text)
    if rewritten:
        vouch_content = rewritten
    else:
        vouch_content = sanitize_text(original_text)

    vouch_message = f"{username}\n\n{vouch_content}"

    # Pre-store before deletion (with placeholder msg id)
    store_vouch(
        from_user_id=message.from_user.id,
        from_username=message.from_user.username,
        from_display_name=message.from_user.first_name,
        to_user_id=None,
        to_username=None,
        to_display_name=None,
        polarity="pos",
        original_text=original_text,
        canonical_text=vouch_message,
        chat_id=message.chat_id,
        message_id=0,
        is_sanitized=True,
    )

    try:
        await message.delete()
    except Exception:
        pass

    try:
        sent = await message.chat.send_message(vouch_message, parse_mode="Markdown")
        update_vouch_message_id(message.chat_id, sent.message_id)
    except Exception:
        pass


async def submit_vouch_via_command(chat: Chat, user: User, args_text: str, polarity: str) -> Tuple[bool, str]:
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
    if not vinfo or not vinfo.get("to_username"):
        return False, "Could not find a target @username. Example: `/vouch @user great courier`"
    vinfo["polarity"] = polarity
    target_username = vinfo.get("to_username", "").lstrip("@") or None

    if check_vouch_duplicate_24h(user.id, target_username, polarity):
        return False, "Looks like you already vouched for that user in the last 24 hours."

    is_sanitized = False
    message_text = ""

    if decision.should_remove:
        rewritten = await rewrite_vouch_with_ai(raw_text)
        sanitized_content = rewritten or sanitize_text(raw_text)
        display_name = f"@{user.username}" if user.username else user.full_name
        message_text = f"{display_name}\n\n{sanitized_content}"
        is_sanitized = True
    else:
        message_text = format_canonical_vouch(vinfo)
        if not message_text:
            return False, "Couldn't format that vouch. Please try adding a clearer @username."

    try:
        sent = await chat.send_message(message_text, parse_mode="Markdown")
    except Exception:
        return False, "Failed to post the vouch. Try again in a moment."

    store_vouch(
        from_user_id=user.id,
        from_username=user.username or "",
        from_display_name=user.first_name,
        to_user_id=None,
        to_username=target_username,
        to_display_name=None,
        polarity=polarity,
        original_text=raw_text,
        canonical_text=message_text,
        chat_id=chat.id,
        message_id=sent.message_id,
        is_sanitized=is_sanitized,
    )

    if is_sanitized:
        stats["vouches_sanitized"] += 1

    if is_sanitized:
        return True, "Vouch sanitized for TOS compliance and posted."
    return True, "Vouch posted."
