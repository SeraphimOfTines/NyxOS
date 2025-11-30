import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rate_limiter import RateLimiter

# Capture original asyncio.sleep to avoid recursion when mocking
original_sleep = asyncio.sleep

class MockTime:
    def __init__(self, start=1000.0):
        self.current = start
    
    def time(self):
        return self.current
    
    async def sleep(self, seconds):
        self.current += seconds
        # Use the original sleep to yield control without triggering the mock again
        await original_sleep(0)

class TestRequestedRateLimits(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.limiter = RateLimiter()
        self.expected_limits = {
            "send_message": (5, 5),
            "delete_message": (5, 1),
            "add_reaction": (1, 0.25),
            "edit_message": (5, 5),
            "direct_message": (5, 5),
            "channel_rename": (2, 600),
            "create_role": (250, 172800),
            "update_presence": (5, 60),
            "identify": (1, 5)
        }

    def test_limit_configuration(self):
        for action, limit_tuple in self.expected_limits.items():
            self.assertIn(action, self.limiter.limits, f"Limit for {action} is missing")
            self.assertEqual(self.limiter.limits[action], limit_tuple, f"Limit mismatch for {action}")

    async def _test_limit_behavior(self, action, limit_count, window, key="test_key"):
        mock_time = MockTime(start=1000.0)
        effective_limit = limit_count - 1 if limit_count > 1 else limit_count
        
        # Use MagicMock because we are providing an async side_effect
        with patch('time.time', side_effect=mock_time.time) as mock_time_func:
            with patch('asyncio.sleep', new_callable=MagicMock) as mock_sleep_func:
                mock_sleep_func.side_effect = mock_time.sleep
                
                # 1. Fill bucket
                for i in range(effective_limit):
                    await self.limiter.wait_for_slot(action, key)
                
                mock_sleep_func.assert_not_called()
                
                # 2. Next request should sleep
                expected_wait = window + 0.05
                
                await self.limiter.wait_for_slot(action, key)
                
                self.assertTrue(mock_sleep_func.called, f"Action {action} did not sleep")
                
                # Check the LAST call argument
                args, _ = mock_sleep_func.call_args
                self.assertAlmostEqual(args[0], expected_wait, places=2, msg=f"Wait time incorrect for {action}")

    async def test_send_message(self):
        await self._test_limit_behavior("send_message", 5, 5)

    async def test_delete_message(self):
        await self._test_limit_behavior("delete_message", 5, 1)

    async def test_add_reaction(self):
        await self._test_limit_behavior("add_reaction", 1, 0.25)

    async def test_edit_message(self):
        await self._test_limit_behavior("edit_message", 5, 5)

    async def test_direct_message(self):
        await self._test_limit_behavior("direct_message", 5, 5)

    async def test_channel_rename(self):
        await self._test_limit_behavior("channel_rename", 2, 600)

    async def test_create_role(self):
        action = "create_role"
        limit = 250
        window = 172800
        effective_limit = 249
        
        mock_time = MockTime(start=1000.0)
        
        with patch('time.time', side_effect=mock_time.time):
            with patch('asyncio.sleep', new_callable=MagicMock) as mock_sleep_func:
                mock_sleep_func.side_effect = mock_time.sleep
                
                for i in range(effective_limit):
                    await self.limiter.wait_for_slot(action, "guild_1")
                    
                    # Advance time periodically to clear global limit (45/1s)
                    if (i + 1) % 40 == 0:
                        mock_time.current += 1.1
                
                mock_sleep_func.assert_not_called()
                
                # 250th request
                await self.limiter.wait_for_slot(action, "guild_1")
                
                self.assertTrue(mock_sleep_func.called)
                args, _ = mock_sleep_func.call_args
                
                wait_time = args[0]
                self.assertGreater(wait_time, 172000, "Should be waiting for nearly 48h")

    async def test_update_presence(self):
        await self._test_limit_behavior("update_presence", 5, 60)

    async def test_identify(self):
        await self._test_limit_behavior("identify", 1, 5)

if __name__ == '__main__':
    unittest.main()