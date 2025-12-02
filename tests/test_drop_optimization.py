import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os
import discord

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from NyxOS import LMStudioBot

class TestDropOptimization(unittest.IsolatedAsyncioTestCase):
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
    async def test_drop_all_at_bottom_updates_inplace(self, mock_mm):
        """Test that 'Drop All' performs in-place edit if bar is already at bottom."""
        
        channel_id = 100
        bar_id = 999
        
        # Setup Active Bar
        self.bot.active_bars = {
            channel_id: {
                "message_id": bar_id, 
                "checkmark_message_id": bar_id,
                "content": "Bar Content",
                "user_id": 555,
                "persisting": False
            }
        }
        
        # Mock Channel and History
        channel = AsyncMock()
        channel.id = channel_id
        
        # Bar IS the last message
        bar_msg = AsyncMock()
        bar_msg.id = bar_id
        bar_msg.content = "Bar Content"
        
        # history iterator
        async def history_gen(limit=1):
            yield bar_msg
        
        channel.history = history_gen
        channel.fetch_message.return_value = bar_msg
        
        self.bot.get_channel.return_value = channel
        
        # Run Drop All
        await self.bot.drop_status_bar(channel_id, move_bar=True, move_check=True)
        
        # Assertions
        
        # 1. Verify Edit called (In-Place Update)
        bar_msg.edit.assert_called()
        
        # 2. Verify Delete NOT called (No Drop)
        bar_msg.delete.assert_not_called()
        channel.send.assert_not_called()

    @patch('NyxOS.memory_manager')
    async def test_drop_all_at_bottom_merges_check(self, mock_mm):
        """Test that 'Drop All' merges checkmark in-place if missing."""
        
        channel_id = 100
        bar_id = 999
        check_id = 888 # Checkmark is separate (above)
        
        # Setup Active Bar
        self.bot.active_bars = {
            channel_id: {
                "message_id": bar_id, 
                "checkmark_message_id": check_id,
                "content": "Bar Content",
                "user_id": 555,
                "persisting": False
            }
        }
        
        channel = AsyncMock()
        channel.id = channel_id
        
        bar_msg = AsyncMock()
        bar_msg.id = bar_id
        bar_msg.content = "Bar Content"
        
        # Old checkmark msg
        check_msg = AsyncMock()
        check_msg.id = check_id
        
        def fetch_side_effect(mid):
            if mid == bar_id: return bar_msg
            if mid == check_id: return check_msg
            raise discord.NotFound(MagicMock(), "msg")
            
        channel.fetch_message.side_effect = fetch_side_effect
        
        # history: Bar is last
        async def history_gen(limit=1):
            yield bar_msg
        channel.history = history_gen
        self.bot.get_channel.return_value = channel
        
        # Run Drop All
        await self.bot.drop_status_bar(channel_id, move_bar=True, move_check=True)
        
        # Assertions
        
        # 1. Bar edited to include checkmark
        bar_msg.edit.assert_called()
        args, kwargs = bar_msg.edit.call_args
        self.assertIn("<a:AllCaughtUp:1289323947082387526>", kwargs['content']) # Checkmark emoji check
        
        # 2. Old checkmark deleted
        check_msg.delete.assert_called()
        
        # 3. No new send
        channel.send.assert_not_called()

if __name__ == '__main__':
    unittest.main()
