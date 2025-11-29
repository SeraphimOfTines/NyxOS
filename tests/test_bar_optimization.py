import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import ui

class TestBarOptimization(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Initialize Bot with mocks
        self.client = NyxOS.LMStudioBot()
        self.client.active_bars = {}
        self.client.bar_drop_cooldowns = {}
        self.client.active_views = {}
        
        # Mock get_channel / fetch_channel
        self.mock_channel = AsyncMock()
        self.mock_channel.id = 12345
        self.mock_channel.guild.id = 67890
        self.mock_channel.send = AsyncMock()
        
        self.client.get_channel = MagicMock(return_value=self.mock_channel)
        self.client.fetch_channel = AsyncMock(return_value=self.mock_channel)
        
        # Mock memory_manager
        self.save_bar_patch = patch('memory_manager.save_bar')
        self.save_bar_mock = self.save_bar_patch.start()
        
        self.delete_bar_patch = patch('memory_manager.delete_bar')
        self.delete_bar_mock = self.delete_bar_patch.start()

    async def asyncTearDown(self):
        self.save_bar_patch.stop()
        self.delete_bar_patch.stop()

    async def test_optimized_drop_check(self):
        """Test that drop_status_bar(move_check=True) edits the bar instead of dropping it."""
        channel_id = 12345
        old_msg_id = 100
        check_msg_id = 200 # Different ID (Check is separate)
        
        # Setup Active Bar
        self.client.active_bars[channel_id] = {
            "message_id": old_msg_id,
            "checkmark_message_id": check_msg_id,
            "content": "Test Bar",
            "user_id": 999,
            "persisting": False
        }
        
        # Mock Messages
        old_msg = AsyncMock()
        old_msg.id = old_msg_id
        old_msg.content = "Test Bar"
        
        check_msg = AsyncMock()
        check_msg.id = check_msg_id
        
        async def fetch_side_effect(msg_id):
            if msg_id == old_msg_id: return old_msg
            if msg_id == check_msg_id: return check_msg
            return None
            
        self.mock_channel.fetch_message.side_effect = fetch_side_effect

        # EXECUTE
        await self.client.drop_status_bar(channel_id, move_check=True)
        
        # VERIFY
        # 1. Checkmark deleted?
        check_msg.delete.assert_called_once()
        
        # 2. Bar edited?
        # Content should contain checkmark
        expected_content = f"Test Bar\n{ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}" # sep is newline if not present? No, sep logic: " " if "\n" not in content. 
        # "Test Bar" has no newline. So sep is " ".
        # Wait, code says: sep = "\n" if "\n" in base_content else " "
        expected_content_space = f"Test Bar {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
        
        # We need to check what edit was called with.
        call_args = old_msg.edit.call_args
        self.assertIsNotNone(call_args)
        self.assertIn(expected_content_space, call_args.kwargs['content'])
        
        # 3. Bar NOT deleted?
        old_msg.delete.assert_not_called()
        
        # 4. New Message NOT sent?
        self.mock_channel.send.assert_not_called()
        
        # 5. State Updated?
        self.assertEqual(self.client.active_bars[channel_id]["checkmark_message_id"], old_msg_id)
        self.save_bar_mock.assert_called()

    async def test_standard_drop(self):
        """Test that drop_status_bar(move_check=False) still drops (deletes/resends)."""
        channel_id = 12345
        old_msg_id = 100
        
        # Setup Active Bar
        self.client.active_bars[channel_id] = {
            "message_id": old_msg_id,
            "checkmark_message_id": old_msg_id,
            "content": "Test Bar",
            "user_id": 999,
            "persisting": False
        }
        
        old_msg = AsyncMock()
        self.mock_channel.fetch_message.return_value = old_msg
        
        # EXECUTE
        await self.client.drop_status_bar(channel_id, move_check=False)
        
        # VERIFY
        # Standard Drop Logic:
        # 1. Split (Edit old to be checkmark if same ID)
        old_msg.edit.assert_called() # Becomes checkmark
        old_msg.delete.assert_not_called()
        
        # 2. New Message SENT
        self.mock_channel.send.assert_called()

    async def test_fallback_on_error(self):
        """Test that optimized drop falls back to standard delete/resend if edit fails."""
        channel_id = 12345
        old_msg_id = 100
        check_msg_id = 200
        
        self.client.active_bars[channel_id] = {
            "message_id": old_msg_id,
            "checkmark_message_id": check_msg_id,
            "content": "Test Bar",
            "user_id": 999,
            "persisting": False
        }
        
        # Mock fetch to fail (simulate deleted message)
        self.mock_channel.fetch_message.side_effect = Exception("Not Found")
        
        # EXECUTE
        await self.client.drop_status_bar(channel_id, move_check=True)
        
        # VERIFY
        # Edit failed (raised exception in try block), should go to fallback.
        # Fallback: Sends new message
        self.mock_channel.send.assert_called()

if __name__ == '__main__':
    unittest.main()
