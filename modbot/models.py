from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModerationDecision:
    should_remove: bool
    reason: str
    severity: str  # "critical" | "high" | "medium" | "low"
    is_vouch: bool


@dataclass
class UserViolation:
    reason: str
    severity: str
    timestamp: float  # epoch seconds

