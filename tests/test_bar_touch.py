import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import sys
import os

sys.path.append(os.getcwd())

from NyxOS import LMStudioBot
import ui

# Helper for async iteration
class AsyncIter:
    def __init__(self, items):
        self.items = list(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

class TestBarTouchHandler:
    
    @pytest.mark.asyncio
    async def test_addbar_uses_db_prefix_and_scans(self):
        """
        Verifies /addbar:
        1. Scans and deletes existing bars.
        2. Fetches last prefix from DB.
        3. Calls save_bar with correct params.
        4. Calls handle_bar_touch (sync console).
        """
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=PropertyMock) as mock_user, \
             patch('memory_manager.get_bar') as mock_get_bar, \
             patch('memory_manager.get_master_bar', return_value="Master Content"), \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('memory_manager.add_bar_whitelist') as mock_whitelist, \
             patch('ui.BAR_PREFIX_EMOJIS', ["<a:Speed1:>"]), \
             patch('helpers.is_authorized', return_value=True): # Mock Auth
             
            mock_user.return_value = MagicMock(id=999)
            
            bot = LMStudioBot()
            bot.handle_bar_touch = AsyncMock()
            
            # Mock Interaction
            interaction = MagicMock()
            interaction.user.id = 123
            interaction.channel_id = 100
            interaction.guild_id = 500
            interaction.response.defer = AsyncMock()
            interaction.edit_original_response = AsyncMock()
            interaction.delete_original_response = AsyncMock()
            interaction.followup.send = AsyncMock()
            
            # Mock Channel History (Simulation of existing bar)
            mock_msg = MagicMock()
            mock_msg.author.id = 999
            mock_msg.content = "<a:Speed1:> Bar"
            mock_msg.components = [] # Simplify
            mock_msg.delete = AsyncMock()
            
            # Use AsyncIter helper for history
            interaction.channel.history.return_value = AsyncIter([mock_msg])
            
            interaction.channel.send = AsyncMock()
            sent_msg = MagicMock()
            sent_msg.id = 700
            interaction.channel.send.return_value = sent_msg
            
            # Mock DB return (Last known state was Speed 2)
            mock_get_bar.return_value = {
                "current_prefix": "<a:Speed2:>",
                "persisting": True,
                "content": "<a:Speed2:> Master Content"
            }
            
            import NyxOS
            # We need to mock `client` inside NyxOS module because the function uses global `client`.
            with patch('NyxOS.client', bot):
                await NyxOS.addbar_command.callback(interaction)
            
            # Assertions
            
            # 1. Scan and Delete
            mock_msg.delete.assert_called_once()
            
            # 2. DB Prefix Used
            # Check the content sent to channel
            args, _ = interaction.channel.send.call_args
            assert "<a:Speed2:>" in args[0]
            assert "Master Content" in args[0]
            
            # 3. Save Bar
            mock_save_bar.assert_called_once()
            call_args = mock_save_bar.call_args
            args = call_args[0]
            kwargs = call_args[1]
            
            assert args[5] is True # persisting
            assert kwargs['current_prefix'] == "<a:Speed2:>"
            assert kwargs['checkmark_message_id'] == 700
            
            # 4. Touch Event
            bot.handle_bar_touch.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_speed1_calls_save_bar_correctly(self):
        """
        Verifies update_bar_prefix calls save_bar with checkmark_message_id.
        """
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=PropertyMock) as mock_user, \
             patch('memory_manager.save_bar') as mock_save_bar:
             
            mock_user.return_value = MagicMock(id=999)
            bot = LMStudioBot()
            bot.handle_bar_touch = AsyncMock()
            
            interaction = MagicMock()
            interaction.channel_id = 100
            interaction.user.id = 123
            interaction.response.send_message = AsyncMock()
            
            # Setup active bars state
            bot.active_bars = {
                100: {
                    "message_id": 500,
                    "checkmark_message_id": 500,
                    "content": "Old Content",
                    "user_id": 123,
                    "persisting": False
                }
            }
            
            # Mock fetch_message
            mock_msg = MagicMock()
            mock_msg.id = 500
            mock_msg.edit = AsyncMock()
            interaction.channel.fetch_message = AsyncMock(return_value=mock_msg)
            
            # Mock find_last_bar_content
            bot.find_last_bar_content = AsyncMock(return_value="<a:Speed0:> Content")
            
            # Execute
            await bot.update_bar_prefix(interaction, "<a:Speed1:>")
            
            # Verify Save Bar
            mock_save_bar.assert_called_once()
            
            # Positional check: save_bar(..., checkmark_message_id=active_msg.id)
            args = mock_save_bar.call_args[0]
            kwargs = mock_save_bar.call_args[1]
            
            # In update_bar_prefix code, we passed checkmark_message_id as a KWARG in the fix.
            # memory_manager.save_bar definition: def save_bar(..., checkmark_message_id=None)
            
            # Let's check if it was passed as kwarg or positional based on how we updated NyxOS.py
            # We updated it to pass checkmark_message_id=active_msg.id (kwarg)
            
            assert kwargs['checkmark_message_id'] == 500
            
            # Verify Touch
            bot.handle_bar_touch.assert_called_once_with(100)