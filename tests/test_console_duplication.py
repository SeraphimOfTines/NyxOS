import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os
import discord

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from NyxOS import LMStudioBot

class TestConsoleDuplicationFix(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = LMStudioBot()
        # self.bot.user = MagicMock() # Read-only
        self.bot._connection = MagicMock()
        self.bot._connection.user = MagicMock()
        self.bot._connection.user.id = 12345
        self.bot.add_view = MagicMock()
        self.bot._register_view = MagicMock()
        self.bot.tree = MagicMock()
        self.bot.get_channel = MagicMock()
        
        # Mock Limiter
        import services
        services.service = MagicMock()
        services.service.limiter = MagicMock()
        services.service.limiter.wait_for_slot = AsyncMock()

    @patch('NyxOS.memory_manager')
    async def test_update_console_status_recovers_from_http_error(self, mock_mm):
        """Test that a transient HTTPException does NOT duplicate the message in memory."""
        
        # Setup: 1 existing console message
        channel = AsyncMock()
        channel.id = 999
        existing_msg = AsyncMock()
        existing_msg.id = 100
        existing_msg.content = "Old Content"
        existing_msg.channel = channel
        
        self.bot.console_progress_msgs = [existing_msg]
        
        # Setup Data: 1 active bar (triggers 1 line update)
        mock_mm.get_bar_whitelist.return_value = ["123"]
        self.bot.active_bars = {123: {"content": "Bar"}}
        
        # Mock Edit to FAIL with HTTPException
        existing_msg.edit.side_effect = discord.HTTPException(
            response=MagicMock(status=503, reason="Service Unavailable"), 
            message="Transient Error"
        )
        
        # Mock Send (should NOT be called for transient error)
        channel.send = AsyncMock()
        
        # Run Update
        await self.bot.update_console_status()
        
        # Assertions
        
        # 1. Verify Edit was attempted
        existing_msg.edit.assert_called()
        
        # 2. Verify Send was NOT called (This is the key fix)
        channel.send.assert_not_called()
        
        # 3. Verify existing message is still in the list
        self.assertEqual(len(self.bot.console_progress_msgs), 1)
        self.assertEqual(self.bot.console_progress_msgs[0].id, existing_msg.id)

    @patch('NyxOS.memory_manager')
    async def test_update_console_status_recreates_on_not_found(self, mock_mm):
        """Test that NotFound error DOES recreate the message."""
        
        # Setup
        channel = AsyncMock()
        channel.id = 999
        existing_msg = AsyncMock()
        existing_msg.id = 100
        existing_msg.channel = channel
        
        self.bot.console_progress_msgs = [existing_msg]
        mock_mm.get_bar_whitelist.return_value = ["123"]
        self.bot.active_bars = {123: {"content": "Bar"}}
        
        # Mock Edit to FAIL with NotFound
        existing_msg.edit.side_effect = discord.NotFound(
            response=MagicMock(), message="Not Found"
        )
        
        # Mock Send to succeed (returning new message)
        new_msg = AsyncMock()
        new_msg.id = 200
        channel.send.return_value = new_msg
        
        # Run Update
        await self.bot.update_console_status()
        
        # Assertions
        existing_msg.edit.assert_called()
        channel.send.assert_called() # Should recreate
        
        # List should now contain the NEW message
        self.assertEqual(len(self.bot.console_progress_msgs), 1)
        self.assertEqual(self.bot.console_progress_msgs[0].id, new_msg.id)

if __name__ == '__main__':
    unittest.main()
