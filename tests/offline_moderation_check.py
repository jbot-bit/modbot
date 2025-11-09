"""
Offline sanity tests for the refactored moderation bot.

This avoids Telegram/network calls and checks:
- Moderation decision pipeline
- Vouch detection paths (clean/dirty decision only)
- Rate limiting behavior (track_user_activity)

Run: python tests/offline_moderation_check.py
"""
import asyncio
import os
import sys
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modbot.engine.orchestrator import analyze_message
from moderation import is_vouch, track_user_activity


async def main():
    uid = 12345
    cases = [
        ("Hello everyone, great day!", "safe"),
        ("+vouch @seller legit and responsive", "+vouch clean"),
        ("+vouch @seller buy weed cheap", "+vouch dirty (illegal keyword)"),
        ("Check this link bit.ly/free-eth", "scam link"),
        ("kys", "harassment keyword"),
    ]

    print("== Moderation Decisions ==")
    for text, label in cases:
        decision = await analyze_message(text, uid)
        print(f"[{label:28}] remove={decision.should_remove} sev={decision.severity} vouch={decision.is_vouch} reason={decision.reason}")

    print("\n== Vouch Detector ==")
    vouch_samples = [
        "+rep @alice very legit",
        "vouch for @bob trusted",
        "neg vouch @scammer do not recommend",
        "random text @name",
    ]
    for s in vouch_samples:
        print(f"{s:45} -> {is_vouch(s)}")

    print("\n== Rate Limiting ==")
    # 6 messages within 10 seconds should trigger limit (threshold=5/10s)
    violations = []
    for i in range(6):
        is_violation, reason = track_user_activity(uid, f"msg {i}")
        if is_violation:
            violations.append((i, reason))
    print(f"message flood triggered: {len(violations) > 0}, details={violations}")


if __name__ == "__main__":
    asyncio.run(main())
