from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from modbot.models import UserViolation
from config import MAX_STRIKES, STRIKE_RESET_HOURS


_user_strikes: Dict[int, Dict] = defaultdict(lambda: {
    "strikes": 0,
    "last_violation": None,
    "violations": [],  # List[UserViolation]
})


def reset_if_needed(user_id: int) -> None:
    data = _user_strikes[user_id]
    if data["last_violation"] and data["strikes"] > 0:
        if datetime.now() - data["last_violation"] > timedelta(hours=STRIKE_RESET_HOURS):
            data["strikes"] = 0
            data["violations"] = []


def record_violation(user_id: int, reason: str, severity: str) -> int:
    reset_if_needed(user_id)
    data = _user_strikes[user_id]
    data["strikes"] += 1
    data["last_violation"] = datetime.now()
    data["violations"].append(UserViolation(reason=reason, severity=severity, timestamp=datetime.now().timestamp()))
    return data["strikes"]


def get_user_status(user_id: int) -> Dict:
    reset_if_needed(user_id)
    data = _user_strikes[user_id]
    return {
        "strikes": data["strikes"],
        "last_violation": data["last_violation"],
        "violations": data["violations"],
        "max_strikes": MAX_STRIKES,
        "reset_hours": STRIKE_RESET_HOURS,
    }

