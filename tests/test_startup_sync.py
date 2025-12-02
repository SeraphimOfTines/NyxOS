import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from NyxOS import LMStudioBot
import ui

class TestStartupSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = LMStudioBot()
        self.bot._connection = MagicMock()
        self.bot._connection.user = MagicMock()
        self.bot._connection.user.id = 12345
        self.bot.add_view = MagicMock()
        self.bot._register_view = MagicMock()

    @patch('NyxOS.memory_manager')
    async def test_verify_and_restore_bars_syncs_db(self, mock_mm):
        """Test that verify_and_restore_bars updates DB if message content differs."""
        
        # 1. Setup Active Bars (Stale State: Idle)
        channel_id = 1001
        msg_id = 2001
        idle_emoji = "<a:NotWatching:1301840196966285322>"
        fast_emoji = "<a:WatchingClosely:1301838354832425010>"
        
        self.bot.active_bars = {
            channel_id: {
                "message_id": msg_id,
                "user_id": 555,
                "content": f"{idle_emoji} Bar Content",
                "current_prefix": idle_emoji,
                "persisting": True,
                "has_notification": False,
                "checkmark_message_id": msg_id
            }
        }
        
        # 2. Mock Channel and Message (Live State: Fast)
        mock_channel = AsyncMock()
        mock_msg = AsyncMock()
        mock_msg.id = msg_id
        mock_msg.content = f"{fast_emoji} Bar Content"
        mock_msg.guild.id = 999
        
        mock_channel.fetch_message.return_value = mock_msg
        
        # Mock fetch_channel to return our mock channel
        self.bot.get_channel = MagicMock(return_value=mock_channel)
        
        # 3. Run Verification
        await self.bot.verify_and_restore_bars()
        
        # 4. Assertions
        
        # Ensure fetch_message was called
        mock_channel.fetch_message.assert_called_with(msg_id)
        
        # Ensure DB was updated (save_bar called with fast_emoji)
        mock_mm.save_bar.assert_called()
        args, kwargs = mock_mm.save_bar.call_args
        
        # Check 'current_prefix' arg
        self.assertEqual(kwargs['current_prefix'], fast_emoji)
        self.assertEqual(args[4], mock_msg.content) # content
        
        # Ensure in-memory active_bars updated
        self.assertEqual(self.bot.active_bars[channel_id]["current_prefix"], fast_emoji)
        self.assertEqual(self.bot.active_bars[channel_id]["content"], mock_msg.content)

    @patch('NyxOS.memory_manager')
    async def test_verify_and_restore_bars_no_sync_if_same(self, mock_mm):
        """Test that verify_and_restore_bars does NOT update DB if content matches."""
        
        channel_id = 1001
        msg_id = 2001
        idle_emoji = "<a:NotWatching:1301840196966285322>"
        
        self.bot.active_bars = {
            channel_id: {
                "message_id": msg_id,
                "user_id": 555,
                "content": f"{idle_emoji} Bar Content",
                "current_prefix": idle_emoji,
                "persisting": True
            }
        }
        
        mock_channel = AsyncMock()
        mock_msg = AsyncMock()
        mock_msg.id = msg_id
        mock_msg.content = f"{idle_emoji} Bar Content"
        mock_msg.guild.id = 999
        
        mock_channel.fetch_message.return_value = mock_msg
        self.bot.get_channel = MagicMock(return_value=mock_channel)
        
        await self.bot.verify_and_restore_bars()
        
        # Ensure save_bar NOT called
        mock_mm.save_bar.assert_not_called()

if __name__ == '__main__':
    unittest.main()
