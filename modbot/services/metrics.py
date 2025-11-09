from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict


stats: Dict = {
    "total_removed": 0,
    "last_24h": 0,
    "violations": defaultdict(int),
    "severity_counts": defaultdict(int),
    "groups": set(),
    "last_reset": datetime.now(),
    "users_warned": 0,
    "users_muted": 0,
    "vouches_sanitized": 0,
}


def touch_group(group_id: int) -> None:
    stats["groups"].add(group_id)


def roll_24h_if_needed() -> None:
    if datetime.now() - stats["last_reset"] > timedelta(hours=24):
        stats["last_24h"] = 0
        stats["last_reset"] = datetime.now()

