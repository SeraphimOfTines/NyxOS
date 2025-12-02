import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import asyncio

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock config BEFORE importing NyxOS
sys.modules['config'] = MagicMock()
sys.modules['config'].LOGS_DIR = "logs"
sys.modules['config'].SHUTDOWN_FLAG_FILE = "shutdown.flag"
sys.modules['config'].RESTART_META_FILE = "restart_metadata.json"
sys.modules['config'].HEARTBEAT_FILE = "heartbeat.txt"
sys.modules['config'].COMMAND_STATE_FILE = "command_state.hash"
sys.modules['config'].LM_STUDIO_URL = "http://localhost:1234"
sys.modules['config'].STARTUP_CHANNEL_ID = 123456789
sys.modules['config'].DATABASE_FILE = ":memory:" 

# Mock discord
sys.modules['discord'] = MagicMock()
sys.modules['discord.app_commands'] = MagicMock()

# Mock dropbox
sys.modules['dropbox'] = MagicMock()
sys.modules['dropbox.files'] = MagicMock()
sys.modules['dropbox.exceptions'] = MagicMock()

from NyxOS import LMStudioBot
import discord

class TestBarPersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Patch discord.Client.__init__ to do nothing so we can instantiate LMStudioBot safely
        with patch('discord.Client.__init__', return_value=None):
            self.bot = LMStudioBot()
            
            # Manually initialize needed attributes typically set by super().__init__ or in __init__
            self.bot.user = MagicMock()
            self.bot.user.id = 123
            self.bot.active_bars = {}
            self.bot.loop = asyncio.get_event_loop()
            
            # Mock the methods used in verify_and_restore_bars
            self.bot.get_channel = MagicMock()
            self.bot.fetch_channel = AsyncMock()
            self.bot.add_view = MagicMock()
            self.bot._register_view = MagicMock()
        
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
