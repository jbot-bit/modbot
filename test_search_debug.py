#!/usr/bin/env python3
"""Debug script to test search_vouches functionality."""
import sys
sys.path.insert(0, '.')

from vouch_db import search_vouches
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Test searches
test_queries = [
    "bighazzz",
    "alice",
    "hazzgoods",
    "coastcontra",
    "leon_grillz",
]

for query in test_queries:
    print(f"\n{'='*60}")
    print(f"Searching for: {query}")
    print(f"{'='*60}")
    results = search_vouches(query, chat_id=None, limit=50)
    print(f"Results: {len(results)} vouches found")
    if results:
        for i, vouch in enumerate(results[:3], 1):
            print(f"\n{i}. From: @{vouch.get('from_username')} To: @{vouch.get('to_username')}")
            print(f"   Text: {vouch.get('original_text', '')[:80]}")
    else:
        print("No results found!")
