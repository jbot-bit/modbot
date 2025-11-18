#!/usr/bin/env python3
"""Test script to verify duplicate prevention logic."""
import sys
sys.path.insert(0, '.')

from vouch_db import vouch_exists_by_message_id
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test with known chat and message IDs from the database
test_cases = [
    (-1001234567890, 12345, True),   # Should exist (from earlier test)
    (-1001234567890, 1001, True),    # Should exist
    (-1001234567890, 99999, False),  # Should NOT exist
    (-100000, 12345, False),         # Different chat, should NOT exist
]

print(f"\n{'='*60}")
print("Testing vouch_exists_by_message_id() for duplicate prevention")
print(f"{'='*60}\n")

for chat_id, message_id, expected in test_cases:
    result = vouch_exists_by_message_id(chat_id, message_id)
    status = "✅ PASS" if result == expected else "❌ FAIL"
    print(f"{status}: chat_id={chat_id}, message_id={message_id}")
    print(f"       Expected: {expected}, Got: {result}\n")

print(f"{'='*60}")
print("Duplicate prevention test complete!")
print(f"{'='*60}\n")
