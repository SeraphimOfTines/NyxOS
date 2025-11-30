import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock
from rate_limiter import RateLimiter

@pytest.mark.asyncio
async def test_rate_limiter_capacity_and_buffer():
    """
    Test that the rate limiter respects the limit and reserves one slot.
    Limit: 5/5s -> Effective Limit: 4.
    """
    limiter = RateLimiter()
    # Override limits for testing speed: 5 requests per 1 second
    limiter.limits["test_action"] = (5, 1.0) 
    
    key = "channel_1"
    
    # Fill the bucket (0, 1, 2, 3) -> 4 requests
    # These should be near instantaneous
    start_time = time.time()
    for i in range(4):
        await limiter.wait_for_slot("test_action", key)
    end_time = time.time()
    
    # Should take negligible time (just execution overhead)
    assert end_time - start_time < 0.1, "First 4 requests should be immediate"

    # The 5th request should block
    # We expect it to wait until the first request expires (approx 1.0s from start)
    # Since we just fired them, they are all fresh.
    
    task = asyncio.create_task(limiter.wait_for_slot("test_action", key))
    
    # Wait a bit less than the window to ensure it's still blocked
    await asyncio.sleep(0.5)
    assert not task.done(), "5th request should be blocked due to 'leave 1 open' rule"
    
    # Wait enough for the window to pass (1.0s total window + buffer)
    await asyncio.sleep(0.6) 
    assert task.done(), "5th request should complete after window expires"

@pytest.mark.asyncio
async def test_rate_limiter_independence():
    """
    Test that rate limits are per-key (channel independent).
    """
    limiter = RateLimiter()
    limiter.limits["test_action"] = (2, 1.0) # Effective limit: 1 (leave 1 open)
    
    # Fill Channel A
    await limiter.wait_for_slot("test_action", "channel_A")
    
    # Channel A should be full (effective limit 1 reached)
    # Channel B should be empty
    
    start_time = time.time()
    await limiter.wait_for_slot("test_action", "channel_B")
    end_time = time.time()
    
    assert end_time - start_time < 0.1, "Channel B should not be blocked by Channel A"

@pytest.mark.asyncio
async def test_burst_limit_behavior():
    """
    Test behavior with strict/low limits (Limit 1).
    Effect limit should be 1 (min 1), not 0.
    """
    limiter = RateLimiter()
    # Limit 1 request per 1 second.
    # "Leave 1 open" logic: if limit > 1 else limit.
    # So effective limit should be 1.
    limiter.limits["strict_action"] = (1, 1.0)
    
    key = "burst_test"
    
    # First call: Should pass
    await limiter.wait_for_slot("strict_action", key)
    
    # Second call: Should block
    task = asyncio.create_task(limiter.wait_for_slot("strict_action", key))
    
    await asyncio.sleep(0.5)
    assert not task.done(), "2nd request should block (Limit 1 reached)"
    
    await asyncio.sleep(0.6) # Total > 1.0s
    assert task.done(), "2nd request should pass after expiration"

@pytest.mark.asyncio
async def test_manual_add():
    """
    Test that manual_add correctly fills the bucket.
    """
    limiter = RateLimiter()
    limiter.limits["test_action"] = (5, 1.0) # Effective 4
    key = "manual_test"
    
    # Manually add 4 entries
    for _ in range(4):
        await limiter.manual_add("test_action", key)
        
    # Next wait should block
    task = asyncio.create_task(limiter.wait_for_slot("test_action", key))
    
    await asyncio.sleep(0.1)
    assert not task.done(), "Request should block due to manually added limits"
    
    await asyncio.sleep(1.0)
    assert task.done()
