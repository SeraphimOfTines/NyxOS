import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Helper for async iteration

from tests.mock_utils import AsyncIter

class TestWakeupLogic(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.tree_patcher = patch('discord.app_commands.CommandTree')
        self.tree_patcher.start()
        self.client = NyxOS.LMStudioBot()
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 999
        
        self.client.get_channel = MagicMock()
        self.client.fetch_channel = AsyncMock()
        self.client.active_bars = {}

    def tearDown(self):
        self.tree_patcher.stop()

    async def test_sync_removes_missing_bars(self):
        """Test that verify_and_restore_bars removes bars if missing/404."""
        
        # Setup Active Bars
        self.client.active_bars = {100: {"message_id": 12345, "user_id": 999}}
        
        # Mock Channel fetch to raise NotFound
        mock_ch = AsyncMock()
        mock_ch.history = MagicMock(return_value=AsyncIter([]))
        mock_ch.fetch_message.side_effect = discord.NotFound(MagicMock(), "Gone")
        
        # Setup client mocks
        self.client.get_channel = MagicMock(return_value=mock_ch)
        self.client.fetch_channel = AsyncMock(return_value=mock_ch)
        
        with patch('memory_manager.remove_bar_whitelist') as mock_remove:
            with patch('memory_manager.delete_bar') as mock_delete:
                
                # Run Verify
                await self.client.verify_and_restore_bars()
                
                # Verify Removal
                mock_remove.assert_called_with(100)
                mock_delete.assert_called_with(100)
                # Verify active_bars update
                self.assertNotIn(100, self.client.active_bars)

if __name__ == '__main__':
    unittest.main()