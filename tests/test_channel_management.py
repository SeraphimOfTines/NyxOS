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

class TestChannelManagement(unittest.IsolatedAsyncioTestCase):
    """Tests for Channel Whitelist and Global Chat Management"""
    
    def setUp(self):
        self.test_dir = "tests/temp_chan_mgmt"
        os.makedirs(self.test_dir, exist_ok=True)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_add_channel_authorized(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 123456789012345678
        interaction.guild.get_member.return_value = interaction.user # Mock member fetch
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.get_allowed_channels', return_value=[]):
                with patch('memory_manager.add_allowed_channel') as mock_add:
                    with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                        
                        await NyxOS.add_channel_command.callback(interaction)
                        
                        mock_add.assert_called_with(123456789012345678)
                        interaction.response.send_message.assert_called()
                        args = interaction.response.send_message.call_args[0][0]
                        self.assertIn("✅", args)

    async def test_add_channel_unauthorized(self):
        interaction = AsyncMock()
        interaction.user.id = 999
        interaction.guild.get_member.return_value = interaction.user
        
        with patch('helpers.is_authorized', return_value=False):
             with patch('memory_manager.add_allowed_channel') as mock_add:
                 
                 await NyxOS.add_channel_command.callback(interaction)
                 
                 mock_add.assert_not_called()
                 interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)

    async def test_remove_channel_authorized(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 123456789012345678
        interaction.guild.get_member.return_value = interaction.user
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.get_allowed_channels', return_value=[123456789012345678]):
                with patch('memory_manager.remove_allowed_channel') as mock_remove:
                    with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                        
                        await NyxOS.remove_channel_command.callback(interaction)
                        
                        mock_remove.assert_called_with(123456789012345678)
                        interaction.response.send_message.assert_called()
                        args = interaction.response.send_message.call_args[0][0]
                        self.assertIn("<a:SeraphHyperNo:1331531123851006025>", args)

    async def test_enable_all_global_chat(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.set_server_setting') as mock_set:
                
                await NyxOS.enableall_command.callback(interaction)
                
                mock_set.assert_called_with("global_chat_enabled", True)
                interaction.response.send_message.assert_called_with("✅", ephemeral=True, delete_after=0.5)

    async def test_disable_all_global_chat(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('memory_manager.set_server_setting') as mock_set:
                
                await NyxOS.disableall_command.callback(interaction)
                
                mock_set.assert_called_with("global_chat_enabled", False)
                interaction.response.send_message.assert_called_with("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)