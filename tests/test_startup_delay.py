
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
        
    async def test_sync_console_delay(self):
        """Test that the sync console loop waits 3s between checks."""
        
        # Mock Whitelist
        with patch('memory_manager.get_bar_whitelist', return_value=['100', '200', '300']), \
             patch('asyncio.sleep') as mock_sleep, \
             patch('memory_manager.get_channel_location', return_value=(1, 1)), \
             patch('helpers.is_authorized', return_value=True), \
             patch('NyxOS.client', self.client): # Patch global client
             
             self.client.get_channel = MagicMock()
             
             # Run syncconsole command
             interaction = AsyncMock()
             await NyxOS.syncconsole_command.callback(interaction)
             
             # Verify 3 sleeps of 3.0s
             self.assertEqual(mock_sleep.call_count, 3)
             mock_sleep.assert_called_with(3.0)

if __name__ == '__main__':
    unittest.main()
