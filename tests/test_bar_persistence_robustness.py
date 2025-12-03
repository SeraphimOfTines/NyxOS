import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import asyncio

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.mock_utils import AsyncIter
import NyxOS
import discord
import config

class TestBarPersistence(unittest.IsolatedAsyncioTestCase):
    
    class MockBot(NyxOS.LMStudioBot):
        def __init__(self):
            self.tree = MagicMock()
            self.startup_header_msg = None
            self.startup_bar_msg = None
            self.console_progress_msgs = []
            self.active_bars = {}
            self._connection = MagicMock()
            self._connection.user = MagicMock()
            self._connection.user.id = 123
            self.loop = AsyncMock()
            # Add any other attributes LMStudioBot needs
            self.wait_until_ready = AsyncMock()

    async def asyncSetUp(self):
        # Patch config attributes
        self.config_patcher = patch.multiple('config', 
            LOGS_DIR="logs",
            SHUTDOWN_FLAG_FILE="shutdown.flag",
            RESTART_META_FILE="restart_metadata.json",
            HEARTBEAT_FILE="heartbeat.txt",
            COMMAND_STATE_FILE="command_state.hash",
            LM_STUDIO_URL="http://localhost:1234",
            STARTUP_CHANNEL_ID=123456789,
            DATABASE_FILE=":memory:"
        )
        self.config_patcher.start()
        
        self.bot = self.MockBot()
        
        # Mock the methods used in verify_and_restore_bars
        self.bot.get_channel = MagicMock()
        self.bot.fetch_channel = AsyncMock()
        self.bot.add_view = MagicMock()
        self.bot._register_view = MagicMock()
        
        # Mock history for any channel returned
        async def mock_fetch_channel_side_effect(cid):
            ch = AsyncMock()
            ch.id = cid
            ch.history = MagicMock(return_value=AsyncIter([]))
            return ch
        self.bot.fetch_channel.side_effect = mock_fetch_channel_side_effect
        self.bot.get_channel.side_effect = lambda cid: None # Force fetch
        
    async def asyncTearDown(self):
        self.config_patcher.stop()
        
    async def test_network_error_preserves_bar(self):
        """Test that HTTP/Network errors do NOT delete the bar from DB."""
        # Setup: One active bar
        channel_id = 100
        msg_id = 200
        self.bot.active_bars = {
            channel_id: {"message_id": msg_id, "content": "Test Bar", "user_id": 123}
        }
        
        # Mock Channel & Message Fetch to raise HTTPException
        mock_channel = AsyncMock()
        mock_channel.history = MagicMock(return_value=AsyncIter([]))
        # Mock fetch_message to raise error
        mock_channel.fetch_message.side_effect = discord.HTTPException(response=MagicMock(), message="Network Error")
        
        self.bot.get_channel = MagicMock(return_value=mock_channel)
        self.bot.fetch_channel = AsyncMock(return_value=mock_channel)
        
        # Use patch on the module imported inside NyxOS
        with patch('NyxOS.memory_manager') as mock_mm:
            await self.bot.verify_and_restore_bars()
            
            # Assertions:
            # 1. Bar should still be in active_bars
            self.assertIn(channel_id, self.bot.active_bars)
            
            # 2. Delete should NOT have been called
            mock_mm.delete_bar.assert_not_called()
            
            # 3. View should still have been added (optimistic restore)
            self.bot.add_view.assert_called()

    async def test_forbidden_error_preserves_bar(self):
        """Test that Forbidden (Permission) errors do NOT delete the bar."""
        channel_id = 100
        msg_id = 200
        self.bot.active_bars = {
            channel_id: {"message_id": msg_id, "content": "Test Bar", "user_id": 123}
        }
        
        mock_channel = AsyncMock()
        mock_channel.history = MagicMock(return_value=AsyncIter([]))
        mock_channel.fetch_message.side_effect = discord.Forbidden(response=MagicMock(), message="No Access")
        
        self.bot.get_channel = MagicMock(return_value=mock_channel)
        
        with patch('NyxOS.memory_manager') as mock_mm:
            await self.bot.verify_and_restore_bars()
            self.assertIn(channel_id, self.bot.active_bars)
            mock_mm.delete_bar.assert_not_called()
            self.bot.add_view.assert_called()

    async def test_not_found_deletes_bar(self):
        """Test that NotFound (404) DOES delete the bar."""
        channel_id = 100
        msg_id = 200
        self.bot.active_bars = {
            channel_id: {"message_id": msg_id, "content": "Test Bar", "user_id": 123}
        }
        
        mock_channel = AsyncMock()
        mock_channel.history = MagicMock(return_value=AsyncIter([]))
        mock_channel.fetch_message.side_effect = discord.NotFound(response=MagicMock(), message="Deleted")
        
        self.bot.get_channel = MagicMock(return_value=mock_channel)
        
        with patch('NyxOS.memory_manager') as mock_mm:
            await self.bot.verify_and_restore_bars()
            
            # Assertions:
            # 1. Bar should be REMOVED
            self.assertNotIn(channel_id, self.bot.active_bars)
            
            # 2. Delete MUST be called
            mock_mm.delete_bar.assert_called_with(channel_id)

if __name__ == '__main__':
    unittest.main()