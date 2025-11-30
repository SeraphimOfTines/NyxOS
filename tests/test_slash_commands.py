import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import helpers

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
        client = NyxOS.LMStudioBot()
        client.tree = MagicMock()
        
        # Mock command list
        cmd = MagicMock()
        cmd.name = "test_cmd"
        cmd.description = "desc"
        cmd.nsfw = False
        client.tree.get_commands.return_value = [cmd]
        
        # 1. First Run (No hash file) -> Should Sync
        client.tree.sync = AsyncMock()
        await client.check_and_sync_commands()
        client.tree.sync.assert_called_once()
        
        # 2. Second Run (Hash file exists and matches) -> Should NOT Sync
        client.tree.sync.reset_mock()
        await client.check_and_sync_commands()
        client.tree.sync.assert_not_called()
        
        # 3. Change Command -> Should Sync
        cmd.description = "new desc"
        client.tree.get_commands.return_value = [cmd]
        await client.check_and_sync_commands()
        client.tree.sync.assert_called_once()

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
                mock_client.active_bars = {123: {'message_id': 1, 'content': 'foo', 'user_id': 99}} # Mock dict
                mock_client.get_channel = MagicMock() # Synchronous
                mock_client.get_channel.return_value.name = "Test Channel"
                
                # Patch os.execl and sys.executable
                with patch('os.execl') as mock_execl, \
                     patch('sys.executable', '/usr/bin/python'):
                    
                    # Call the callback directly
                    await NyxOS.reboot_command.callback(interaction)
                    
                    # Assertions
                    # Expect followup because defer was called
                    interaction.followup.send.assert_called() 
                    mock_client.close.assert_called_once()
                    
                    # Verify restart meta file
                    self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                    
                    # Verify os.execl call
                    mock_execl.assert_called()

    async def test_reboot_command_unauthorized(self):
        interaction = AsyncMock()
        interaction.user.id = 999 # Unauthorized
        
        with patch('helpers.is_authorized', return_value=False):
             await NyxOS.reboot_command.callback(interaction)
             
             interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
             # Ensure no reboot
             with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                 mock_client.close.assert_not_called()

    async def test_shutdown_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 456
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                # FIX: Make active_bars a dict, not an AsyncMock
                mock_client.active_bars = {123: {"content": "foo", "message_id": 1}}
                
                with patch('sys.exit') as mock_exit:
                     
                     await NyxOS.shutdown_command.callback(interaction)
                     
                     interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"], ephemeral=False)
                     mock_client.close.assert_called_once()
                     mock_exit.assert_called_with(0)
                     self.assertTrue(os.path.exists(config.SHUTDOWN_FLAG_FILE))
