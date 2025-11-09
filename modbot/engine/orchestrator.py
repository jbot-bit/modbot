from __future__ import annotations

from typing import Tuple

from modbot.models import ModerationDecision

# Reuse existing detection from moderation.py for now
from moderation import check_message as legacy_check_message


async def analyze_message(text: str, user_id: int) -> ModerationDecision:
    """
    Run the moderation pipeline and return a normalized decision.

    This wraps the existing check_message to preserve behavior while
    exposing a stable contract for handlers.
    """
    should_remove, reason, severity, is_vouch = await legacy_check_message(text, user_id)
    return ModerationDecision(
        should_remove=should_remove,
        reason=reason,
        severity=severity,
        is_vouch=is_vouch,
    )

