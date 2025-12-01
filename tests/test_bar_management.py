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

class TestBarManagement(unittest.IsolatedAsyncioTestCase):
    """Tests for Bar Creation and Management"""

    async def test_addbar_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 100
        interaction.guild_id = 555
        interaction.channel.send = AsyncMock()
        
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
                         mock_whitelist.assert_called_with(100)
                         interaction.channel.send.assert_called()
                         
                         # Check active_bars update
                         self.assertIn(100, mock_client.active_bars)
                         self.assertEqual(mock_client.active_bars[100]['message_id'], 999)
                         
                         mock_save.assert_called()

    async def test_removebar_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 100
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.remove_bar_whitelist') as mock_remove_wl:
                with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                    
                    await NyxOS.removebar_command.callback(interaction)
                    
                    mock_remove_wl.assert_called_with(100)
                    mock_client.wipe_channel_bars.assert_called_with(interaction.channel)
                    interaction.response.send_message.assert_called()

    async def test_drop_command_no_bar(self):
        interaction = AsyncMock()
        interaction.channel_id = 100
        
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            mock_client.active_bars = {} # Empty
            
            await NyxOS.drop_command.callback(interaction)
            
            interaction.response.send_message.assert_called()
            args = interaction.response.send_message.call_args[0][0]
            self.assertIn("No active bar", args)

    async def test_drop_command_success(self):
        interaction = AsyncMock()
        interaction.channel_id = 100
        
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            mock_client.active_bars = {100: {}}
            
            await NyxOS.drop_command.callback(interaction)
            
            interaction.response.defer.assert_called()
            mock_client.drop_status_bar.assert_called_with(100, move_bar=True, move_check=True)
            interaction.delete_original_response.assert_called()

    async def test_restore_command_found(self):
        interaction = AsyncMock()
        interaction.channel_id = 100
        
        with patch('memory_manager.get_bar_history', return_value="Old Content"):
             with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                 
                 await NyxOS.restore_command.callback(interaction)
                 
                 mock_client.replace_bar_content.assert_called_with(interaction, "Old Content")

    async def test_restore_command_not_found(self):
        interaction = AsyncMock()
        interaction.channel_id = 100
        
        with patch('memory_manager.get_bar_history', return_value=None):
             with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                 
                 await NyxOS.restore_command.callback(interaction)
                 
                 mock_client.replace_bar_content.assert_not_called()
                 interaction.response.send_message.assert_called()
