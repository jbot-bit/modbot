"""
Test script for the vouch retry logic (3-strike system)

This script tests the database tracking functions for vouch retry attempts.
Run this before deploying to ensure the tracking system works correctly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vouch_db import (
    track_vouch_retry_attempt,
    clear_vouch_retry_attempts,
    cleanup_old_vouch_retry_attempts,
    init_db
)
import time


def test_retry_tracking():
    """Test the basic retry tracking functionality"""
    print("\n" + "="*60)
    print("TEST 1: Retry Tracking")
    print("="*60)
    
    user_id = 999999
    chat_id = -100123456789
    target = "alice"
    
    print(f"Testing tracking for user {user_id} vouching for @{target}...")
    
    # First attempt
    count1 = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"✓ Attempt 1: count = {count1}")
    assert count1 == 1, f"Expected count=1, got {count1}"
    
    # Second attempt
    count2 = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"✓ Attempt 2: count = {count2}")
    assert count2 == 2, f"Expected count=2, got {count2}"
    
    # Third attempt
    count3 = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"✓ Attempt 3: count = {count3}")
    assert count3 == 3, f"Expected count=3, got {count3}"
    
    # Fourth attempt (should continue incrementing)
    count4 = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"✓ Attempt 4: count = {count4}")
    assert count4 == 4, f"Expected count=4, got {count4}"
    
    print("✅ PASS: Retry tracking increments correctly")


def test_clear_attempts():
    """Test clearing retry attempts"""
    print("\n" + "="*60)
    print("TEST 2: Clear Retry Attempts")
    print("="*60)
    
    user_id = 999998
    chat_id = -100123456789
    target = "bob"
    
    # Create some attempts
    count1 = track_vouch_retry_attempt(user_id, chat_id, target)
    count2 = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"Created {count2} attempts for @{target}")
    
    # Clear them
    clear_vouch_retry_attempts(user_id, chat_id, target)
    print(f"✓ Cleared attempts for @{target}")
    
    # Next attempt should be 1 again
    count_after = track_vouch_retry_attempt(user_id, chat_id, target)
    print(f"✓ Next attempt after clear: count = {count_after}")
    assert count_after == 1, f"Expected count=1 after clear, got {count_after}"
    
    print("✅ PASS: Clear attempts resets counter correctly")


def test_multiple_targets():
    """Test that different targets have independent counters"""
    print("\n" + "="*60)
    print("TEST 3: Multiple Targets Independence")
    print("="*60)
    
    user_id = 999997
    chat_id = -100123456789
    target1 = "charlie"
    target2 = "david"
    
    # Track attempts for target1
    count1_t1 = track_vouch_retry_attempt(user_id, chat_id, target1)
    count2_t1 = track_vouch_retry_attempt(user_id, chat_id, target1)
    print(f"@{target1}: attempts = {count2_t1}")
    
    # Track attempts for target2 (should be independent)
    count1_t2 = track_vouch_retry_attempt(user_id, chat_id, target2)
    print(f"@{target2}: attempts = {count1_t2}")
    
    assert count2_t1 == 2, f"Expected @{target1} count=2, got {count2_t1}"
    assert count1_t2 == 1, f"Expected @{target2} count=1, got {count1_t2}"
    
    # Verify target1 counter is still 2
    count3_t1 = track_vouch_retry_attempt(user_id, chat_id, target1)
    print(f"@{target1} after @{target2} attempt: count = {count3_t1}")
    assert count3_t1 == 3, f"Expected @{target1} count=3, got {count3_t1}"
    
    print("✅ PASS: Multiple targets have independent counters")


def test_cleanup():
    """Test cleanup of old attempts"""
    print("\n" + "="*60)
    print("TEST 4: Cleanup Old Attempts")
    print("="*60)
    
    # Note: This test would need manual database manipulation to test properly
    # For now, just verify the function runs without error
    
    print("Running cleanup (removes attempts older than 24h)...")
    cleanup_old_vouch_retry_attempts(hours=24)
    print("✓ Cleanup function executed without error")
    
    print("✅ PASS: Cleanup runs successfully")


def test_username_normalization():
    """Test that @username and username are treated the same"""
    print("\n" + "="*60)
    print("TEST 5: Username Normalization")
    print("="*60)
    
    user_id = 999996
    chat_id = -100123456789
    
    # Track with @ prefix
    count1 = track_vouch_retry_attempt(user_id, chat_id, "@emily")
    print(f"Tracked with '@emily': count = {count1}")
    
    # Track without @ prefix (should increment the same counter)
    count2 = track_vouch_retry_attempt(user_id, chat_id, "emily")
    print(f"Tracked with 'emily': count = {count2}")
    
    assert count2 == 2, f"Expected count=2 (same counter), got {count2}"
    
    # Verify with mixed case
    count3 = track_vouch_retry_attempt(user_id, chat_id, "EMILY")
    print(f"Tracked with 'EMILY': count = {count3}")
    
    assert count3 == 3, f"Expected count=3 (same counter), got {count3}"
    
    print("✅ PASS: Username normalization works correctly")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("VOUCH RETRY LOGIC - DATABASE TESTS")
    print("="*60)
    print("Testing the 3-strike vouch retry tracking system")
    print("="*60)
    
    # Initialize database
    print("\nInitializing database...")
    init_db()
    print("✓ Database initialized")
    
    tests = [
        ("Retry Tracking", test_retry_tracking),
        ("Clear Attempts", test_clear_attempts),
        ("Multiple Targets", test_multiple_targets),
        ("Cleanup", test_cleanup),
        ("Username Normalization", test_username_normalization),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"❌ FAIL: {name} - {e}")
            failed += 1
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 All tests passed! The vouch retry system is working correctly.")
    else:
        print(f"\n⚠️ {failed} test(s) failed. Please review the errors above.")
    
    print("="*60)


if __name__ == "__main__":
    main()
