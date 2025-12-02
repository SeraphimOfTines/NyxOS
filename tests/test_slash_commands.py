import unittest
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
import sys
import os
import NyxOS
import config
import ui

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestServerAdmin(unittest.IsolatedAsyncioTestCase):
    """Tests for Server Administration features"""
    
    def setUp(self):
        self.test_dir = "tests/temp_admin"
        os.makedirs(self.test_dir, exist_ok=True)
        config.COMMAND_STATE_FILE = os.path.join(self.test_dir, "command_state.hash")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_smart_sync(self):
        with patch('discord.app_commands.CommandTree'):
            client = NyxOS.LMStudioBot()
            client.tree = AsyncMock()
            client.get_tree_hash = MagicMock(return_value="hash123")
            
            # Case 1: Hash Mismatch
            with patch("builtins.open", mock_open(read_data="oldhash")), \
                 patch("os.path.exists", return_value=True):
                
                await client.check_and_sync_commands()
                client.tree.sync.assert_called_once()
            
            # Case 2: Hash Match
            client.tree.sync.reset_mock()
            with patch("builtins.open", mock_open(read_data="hash123")), \
                 patch("os.path.exists", return_value=True):
                
                await client.check_and_sync_commands()
                client.tree.sync.assert_not_called()

class TestCommands(unittest.IsolatedAsyncioTestCase):
    """Tests for Slash Commands"""
    
    def setUp(self):
        self.test_dir = "tests/temp_commands"
        os.makedirs(self.test_dir, exist_ok=True)
        config.RESTART_META_FILE = os.path.join(self.test_dir, "restart_meta.json")
        config.SHUTDOWN_FLAG_FILE = os.path.join(self.test_dir, "shutdown.flag")
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_reboot_command_authorized(self):
        # Mock Interaction
        interaction = MagicMock()
        interaction.user.id = 123
        interaction.channel_id = 456
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        
        # Patch helpers.is_authorized
        with patch('helpers.is_authorized', return_value=True):
            # Patch NyxOS.client
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                
                # Call the callback directly
                await NyxOS.reboot_command.callback(interaction)
                
                # Assertions
                # Verify that the sequence was initiated
                mock_client.perform_shutdown_sequence.assert_called_once_with(interaction, restart=True)

    async def test_reboot_command_unauthorized(self):
        interaction = AsyncMock()
        interaction.user.id = 999 # Unauthorized
        
        with patch('helpers.is_authorized', return_value=False):
             await NyxOS.reboot_command.callback(interaction)
             
             interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
             # Ensure no reboot
             with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                 mock_client.perform_shutdown_sequence.assert_not_called()

    async def test_shutdown_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 456
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                
                 await NyxOS.shutdown_command.callback(interaction)
                 
                 # Verify sequence initiated
                 mock_client.perform_shutdown_sequence.assert_called_once_with(interaction, restart=False)
