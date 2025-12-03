import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import memory_manager

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_utils import AsyncIter

class TestBarManagement(unittest.IsolatedAsyncioTestCase):
    """Tests for Bar Creation and Management"""

    async def test_addbar_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 123456789012345678
        interaction.guild_id = 555
        interaction.channel.send = AsyncMock()
        
        # Mock history to return an empty async iterator
        interaction.channel.history = MagicMock(return_value=AsyncIter([]))
        
        # Create a fake message return for send
        mock_msg = MagicMock()
        mock_msg.id = 999
        interaction.channel.send.return_value = mock_msg
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.add_bar_whitelist') as mock_whitelist:
                with patch('memory_manager.save_bar') as mock_save:
                    with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                         # Mock active_bars as a dict
                         mock_client.active_bars = {}
                         # Mock register method
                         mock_client._register_bar_message = MagicMock()
                         
                         await NyxOS.addbar_command.callback(interaction)
                         
                         # Verifications
                         mock_whitelist.assert_called_with(123456789012345678)
                         interaction.channel.send.assert_called()
                         
                         # Check active_bars update
                         self.assertIn(123456789012345678, mock_client.active_bars)
                         self.assertEqual(mock_client.active_bars[123456789012345678]['message_id'], 999)
                         
                         mock_save.assert_called()

    async def test_removebar_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 123456789012345678
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('memory_manager.remove_bar_whitelist') as mock_remove_wl, \
             patch('memory_manager.delete_bar') as mock_delete:
                with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                    mock_client.active_bars = {}                        
                                                                        
                    await NyxOS.removebar_command.callback(interaction) 
                    
                    # Verifications
                    interaction.response.defer.assert_called_with(ephemeral=True)
                    mock_remove_wl.assert_called_with(123456789012345678)
                    mock_client.wipe_channel_bars.assert_called_with(interaction.channel)
                    
                    # Updated: removebar does NOT send checkmark anymore, just deletes response
                    interaction.edit_original_response.assert_not_called()
                    interaction.delete_original_response.assert_called()

    async def test_drop_command_no_bar(self):
        interaction = AsyncMock()
        interaction.channel_id = 123456789012345678
        
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            mock_client.active_bars = {} # Empty
            
            await NyxOS.drop_command.callback(interaction)
            
            interaction.response.send_message.assert_called()
            args = interaction.response.send_message.call_args[0][0]
            self.assertIn("No active bar", args)

    async def test_drop_command_success(self):
        interaction = AsyncMock()
        interaction.channel_id = 123456789012345678
        
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            mock_client.active_bars = {123456789012345678: {}}
            
            await NyxOS.drop_command.callback(interaction)
            
            interaction.response.defer.assert_called()
            mock_client.drop_status_bar.assert_called_with(123456789012345678, move_bar=True, move_check=True)
            interaction.delete_original_response.assert_called()