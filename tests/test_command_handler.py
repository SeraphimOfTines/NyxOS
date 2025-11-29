import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import json

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import command_handler
import config
import ui

class TestCommandHandler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_message = MagicMock()
        self.mock_message.channel.send = AsyncMock()
        self.mock_client.close = AsyncMock()
        
        # Default Author
        self.mock_message.author.id = 12345

    # --- test_authorization ---
    async def test_authorization_failed(self):
        """Mock a user without admin roles -> Verify NOT_AUTHORIZED response."""
        self.mock_message.content = "&addchannel"
        self.mock_message.author.id = 99999 # Not in config
        self.mock_message.author.roles = [] # No roles

        # Mock config IDs
        with patch('config.ADMIN_ROLE_IDS', [88888]), \
             patch('config.SPECIAL_ROLE_IDS', [77777]):
            
            await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
            
            self.mock_message.channel.send.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])

    async def test_authorization_success(self):
        """Mock a user with admin roles -> Verify command proceeds."""
        self.mock_message.content = "&addchannel"
        self.mock_message.channel.id = 111
        
        # Mock Authorization to pass
        with patch('helpers.is_authorized', return_value=True):
             # Mock memory_manager to avoid real DB calls
            with patch('command_handler.memory_manager.add_allowed_channel') as mock_add:
                
                await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
                
                # Verify add_channel was called (proving auth passed)
                mock_add.assert_called_with(111)
                # Verify success message
                self.mock_message.channel.send.assert_called()
                args = self.mock_message.channel.send.call_args[0][0]
                self.assertIn("I'll talk in this channel", args)

    # --- test_add_remove_channel ---
    async def test_add_remove_channel(self):
        """Verify config.ALLOWED_CHANNEL_IDS is updated (via memory_manager mocks)."""
        # Test Add
        self.mock_message.content = "&addchannel"
        self.mock_message.channel.id = 101
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('command_handler.memory_manager.add_allowed_channel') as mock_add, \
                 patch('command_handler.memory_manager.get_allowed_channels', return_value=[999]):
                
                await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
                mock_add.assert_called_with(101)

        # Test Remove
        self.mock_message.content = "&removechannel"
        self.mock_message.channel.id = 101
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('command_handler.memory_manager.remove_allowed_channel') as mock_remove, \
                 patch('command_handler.memory_manager.get_allowed_channels', return_value=[101]):
                
                await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
                mock_remove.assert_called_with(101)

    # --- test_reboot_shutdown ---
    async def test_reboot_shutdown(self):
        """
        Verify they write the correct state files (restart_meta.json, shutdown_flag).
        """
        # REBOOT
        self.mock_message.content = "&reboot"
        self.mock_message.channel.id = 555
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open()) as mock_file, \
             patch('os.execl') as mock_exec, \
             patch('os.fsync') as mock_fsync:
            
            await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
            
            # Verify Meta File Write
            mock_file.assert_called_with(config.RESTART_META_FILE, "w")
            handle = mock_file()
            # Check that we wrote valid JSON
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            self.assertIn('"channel_id": 555', written_data)
            
            # Verify Client Close and Execl
            self.mock_client.close.assert_called()
            mock_exec.assert_called()

        # SHUTDOWN
        self.mock_message.content = "&shutdown"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open()) as mock_file, \
             patch('sys.exit') as mock_exit:
            
            await command_handler.handle_prefix_command(self.mock_client, self.mock_message)
            
            # Verify Flag File Write
            mock_file.assert_called_with(config.SHUTDOWN_FLAG_FILE, "w")
            handle = mock_file()
            handle.write.assert_called_with("shutdown")
            
            # Verify Exit
            self.mock_client.close.assert_called()
            mock_exit.assert_called_with(0)

if __name__ == '__main__':
    unittest.main()
