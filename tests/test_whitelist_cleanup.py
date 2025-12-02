import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from NyxOS import LMStudioBot

class TestWhitelistCleanup(unittest.IsolatedAsyncioTestCase):
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
    @patch('NyxOS.client', new_callable=lambda: LMStudioBot()) # Patch the global client too
    async def test_on_ready_cleans_whitelist(self, mock_client, mock_mm):
        """Test that on_ready removes orphaned whitelist entries."""
        
        # Ensure mock_client matches our setup
        mock_client._connection = self.bot._connection
        
        # Setup Data
        valid_cid = 100
        orphan_cid = 200
        
        # Active bars only has valid_cid
        self.bot.active_bars = {valid_cid: {"content": "stuff"}}
        mock_mm.get_all_bars.return_value = self.bot.active_bars
        
        # Whitelist has both
        mock_mm.get_bar_whitelist.return_value = [str(valid_cid), str(orphan_cid)]
        
        # Mock other dependencies
        self.bot.verify_and_restore_bars = AsyncMock()
        self.bot.initialize_console_channel = AsyncMock()
        self.bot.update_console_status = AsyncMock()
        self.bot.check_and_sync_commands = AsyncMock()
        
        # Run on_ready
        # We need to patch 'NyxOS.client' to be 'self.bot' inside the function if it uses 'client'
        # But wait, NyxOS.py uses 'client' global variable in on_ready logging.
        # The patch above creates a new instance. Let's make sure we use self.bot
        
        with patch('NyxOS.client', self.bot):
            await self.bot.on_ready()
        
        # Assertions
        # remove_bar_whitelist should be called for orphan_cid
        mock_mm.remove_bar_whitelist.assert_called_with(str(orphan_cid))
        
        # Should NOT be called for valid_cid (checking call args list)
        # We iterate over calls to ensure valid_cid wasn't removed
        for call in mock_mm.remove_bar_whitelist.call_args_list:
            args, _ = call
            self.assertNotEqual(args[0], str(valid_cid))

if __name__ == '__main__':
    unittest.main()
