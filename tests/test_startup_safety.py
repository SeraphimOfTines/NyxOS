import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from NyxOS import LMStudioBot

class TestStartupSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = LMStudioBot()
        self.bot._connection = MagicMock()
        self.bot._connection.user = MagicMock()
        self.bot._connection.user.id = 12345
        self.bot.add_view = MagicMock()
        self.bot._register_view = MagicMock()
        # Mock the tree
        self.bot.tree = MagicMock()
        self.bot.tree.get_commands.return_value = [MagicMock(name="nukedatabase")]

    @patch('NyxOS.memory_manager')
    @patch('config.STARTUP_CHANNEL_ID', None)
    async def test_on_ready_does_not_clean_whitelist(self, mock_mm):
        """Test that on_ready does NOT remove whitelist entries even if active_bars is empty."""
        
        # Setup Data
        valid_cid = 100
        orphan_cid = 200
        
        # Active bars is EMPTY (Simulating DB load failure or corruption)
        self.bot.active_bars = {}
        mock_mm.get_all_bars.return_value = {}
        
        # Whitelist has entries
        mock_mm.get_bar_whitelist.return_value = [str(valid_cid), str(orphan_cid)]
        
        # Mock other dependencies
        self.bot.verify_and_restore_bars = AsyncMock()
        self.bot.initialize_console_channel = AsyncMock()
        self.bot.update_console_status = AsyncMock()
        self.bot.check_and_sync_commands = AsyncMock()
        
        # Run on_ready
        with patch('NyxOS.client', self.bot):
            await self.bot.on_ready()
        
        # Assertions
        # remove_bar_whitelist should NEVER be called
        mock_mm.remove_bar_whitelist.assert_not_called()

if __name__ == '__main__':
    unittest.main()
