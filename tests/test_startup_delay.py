
import unittest
from unittest.mock import MagicMock, patch, AsyncMock, call
import sys
import os
import asyncio

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import config

class TestStartupDelay(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.client = NyxOS.LMStudioBot()
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 12345
        
        # Mock basic methods
        self.client.get_channel = MagicMock(return_value=None)
        self.client.fetch_channel = AsyncMock(return_value=None)
        
    async def test_startup_scan_delay_and_skip(self):
        """
        Test that the startup loop:
        1. Waits 8 seconds between scans.
        2. Skips channel ID 99999.
        """
        
        # Define the whitelist with regular channels and the forbidden one
        # 3 valid channels + 1 invalid (99999)
        whitelist = ["1001", "99999", "1002", "1003"]
        
        # Mock Dependencies
        with patch('NyxOS.logger'), \
             patch('NyxOS.client', self.client), \
             patch('NyxOS.memory_manager.get_all_bars', return_value={}), \
             patch('os.path.exists', return_value=False), \
             patch('NyxOS.memory_manager.get_bar_whitelist', return_value=whitelist), \
             patch('NyxOS.memory_manager.get_allowed_channels', return_value=set(map(int, whitelist))), \
             patch('NyxOS.memory_manager.get_master_bar', return_value="System Online"), \
             patch('NyxOS.memory_manager.get_channel_location', return_value=(None, None)), \
             patch('NyxOS.memory_manager.save_channel_location'), \
             patch('NyxOS.memory_manager.save_bar'), \
             patch('NyxOS.config.STARTUP_CHANNEL_ID', None), \
             patch('NyxOS.asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
             patch('NyxOS.ui.WakeupReportView', return_value=MagicMock()):
            
            # Run perform_system_scan
            await self.client.perform_system_scan()
            
            # VERIFICATION
            
            # 1. Check 1.5s delays
            # The loop calls sleep(1.5)
            # We expect 4 calls with 1.5
            
            # Debug: print calls if failed
            # sleeps = [c for c in mock_sleep.call_args_list if c.args[0] == 1.5]
            
            # Just assert we called it with 1.5 at least once per item
            # Note: There might be other sleep calls (e.g. 2.0s fallback, or 1.0s new bar delay)
            # But we simulate DB fetch failure (return None, None) -> Fallback -> 2.0s delay
            # So we expect 1.5s AND 2.0s.
            
            calls_delay = [c for c in mock_sleep.call_args_list if c.args[0] == 8.0]
            self.assertEqual(len(calls_delay), 4, f"Expected 4 sleeps of 8.0s, got {len(calls_delay)}. Calls: {mock_sleep.call_args_list}")
            
            # 2. Check Channel 99999 Skip
            # fetch_channel should be called for 1001, 1002, 1003 but NOT 99999
            # get_channel is tried first, then fetch_channel.
            
            # Gather all calls to get_channel and fetch_channel
            get_calls = [args[0] for args, _ in self.client.get_channel.call_args_list]
            fetch_calls = [args[0] for args, _ in self.client.fetch_channel.call_args_list]
            
            all_attempts = set(get_calls + fetch_calls)
            
            self.assertIn(1001, all_attempts)
            self.assertIn(1002, all_attempts)
            self.assertIn(1003, all_attempts)
            self.assertNotIn(99999, all_attempts, "Channel 99999 should have been skipped before any API call")

if __name__ == '__main__':
    unittest.main()
