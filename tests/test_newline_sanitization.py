import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from tests.mock_utils import AsyncIter
import sys
import os
import NyxOS
import ui
import config

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestNewlineSanitization(unittest.IsolatedAsyncioTestCase):
    """Tests to ensure newlines are stripped from status bar content."""

    def setUp(self):
        # Basic Mock Interaction
        self.interaction = MagicMock()
        self.interaction.user.id = 12345
        self.interaction.guild_id = 67890
        self.interaction.channel_id = 11111
        self.interaction.channel = AsyncMock()
        self.interaction.response = MagicMock()
        self.interaction.response.send_message = AsyncMock()
        self.interaction.response.defer = AsyncMock()
        self.interaction.delete_original_response = AsyncMock()
        self.interaction.edit_original_response = AsyncMock()
        self.interaction.followup = MagicMock()
        self.interaction.followup.send = AsyncMock()

    async def test_global_command_sanitization(self):
        """Test that global_update_bars strips newlines from input."""
        with patch('memory_manager.set_master_bar') as mock_set_bar, \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Use real bot instance (patched init via unittest patch if needed, but here we just instantiate)
            # Since we are in IsolatedAsyncioTestCase, we can try instantiating.
            # But LMStudioBot init connects. We should patch init if we instantiate.
            # Or just mock the method on a MagicMock? No, we want to test the METHOD logic.
            
            with patch('discord.Client.__init__', return_value=None), \
                 patch('discord.app_commands.CommandTree'):
                bot = NyxOS.LMStudioBot()
                bot.active_bars = {100: {"user_id": 123, "message_id": 999, "persisting": False}}
                bot.propagate_master_bar = AsyncMock(return_value=5)

                dirty_content = "My Cool Status\n"
                await bot.global_update_bars(dirty_content)
            
            # Verify set_master_bar was called with CLEAN content
            mock_set_bar.assert_called_once_with("My Cool Status")


    async def test_addbar_command_sanitization(self):
        """Test that /addbar strips newlines from master bar content before using it."""
        with patch('helpers.is_authorized', return_value=True), \
             patch('memory_manager.get_master_bar', return_value="Dirty Master\n"), \
             patch('memory_manager.get_bar', return_value={}), \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('NyxOS.client', new=AsyncMock()) as mock_client:
            
            mock_client.active_bars = {}
            mock_client._register_bar_message = MagicMock()
            mock_client.handle_bar_touch = AsyncMock()
            
            # Mock history
            self.interaction.channel.history = MagicMock(return_value=AsyncIter([]))

            # Execute
            await NyxOS.addbar_command.callback(self.interaction)
            
            # Verify send call
            send_args = self.interaction.channel.send.call_args
            content_sent = send_args[0][0]
            
            self.assertNotIn("\n", content_sent)
            self.assertIn("Dirty Master", content_sent)
            self.assertIn(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], content_sent)

    async def test_propagate_master_bar_sanitization(self):
        """Test that propagate_master_bar strips newlines."""
        client = NyxOS.LMStudioBot()
        client.active_bars = {111: {"message_id": 999, "user_id": 123, "content": "Old Content"}}
        client.get_channel = MagicMock(return_value=self.interaction.channel)
        
        with patch('memory_manager.get_master_bar', return_value="Propagate Dirty\n"), \
             patch('memory_manager.get_bar_whitelist', return_value=[111]), \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Mock fetch_message
            mock_msg = AsyncMock()
            self.interaction.channel.fetch_message.return_value = mock_msg
            
            await client.propagate_master_bar()
            
            # Check edit call
            edit_args = mock_msg.edit.call_args
            content_edited = edit_args.kwargs['content']
            
            self.assertNotIn("\n", content_edited)
            self.assertIn("Propagate Dirty", content_edited)

    async def test_update_bar_prefix_sanitization(self):
        """Test that update_bar_prefix cleans found content."""
        client = NyxOS.LMStudioBot()
        client.find_last_bar_content = AsyncMock(return_value="Found Dirty Content\n")
        client.active_bars = {11111: {"message_id": 999, "user_id": 123, "content": "Old"}}
        
        with patch('memory_manager.save_bar') as mock_save_bar, \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
             
             # Mock fetch message for in-place edit
             mock_msg = AsyncMock()
             self.interaction.channel.fetch_message.return_value = mock_msg
             
             new_prefix = "🔥"
             await client.update_bar_prefix(self.interaction, new_prefix)
             
             # Check edit
             edit_args = mock_msg.edit.call_args
             content_edited = edit_args.kwargs['content']
             
             # Should be "🔥 Found Dirty Content <Checkmark>"
             self.assertNotIn("\n", content_edited)
             self.assertIn("Found Dirty Content", content_edited)

if __name__ == '__main__':
    unittest.main()