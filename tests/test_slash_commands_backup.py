import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import NyxOS
import config

class TestSlashCommands(unittest.TestCase):
    def setUp(self):
        # Setup minimal mocks for Discord objects
        self.interaction = MagicMock()
        self.interaction.user = MagicMock()
        self.interaction.user.id = 12345
        self.interaction.guild = MagicMock()
        self.interaction.response = MagicMock()
        # Make interaction.original_response return an awaitable that returns a message mock
        self.msg_mock = MagicMock()
        self.msg_mock.edit = AsyncMock()
        self.interaction.original_response = AsyncMock(return_value=self.msg_mock)
        self.interaction.response.send_message = AsyncMock()
        
        # Mock config IDs
        config.TEMPLE_GUILD_ID = 100
        config.WM_GUILD_ID = 200
        config.SHRINE_CHANNEL_ID = 300
        
        # Mock Auth
        self.auth_patcher = patch('helpers.is_authorized', return_value=True)
        self.auth_mock = self.auth_patcher.start()

    def tearDown(self):
        self.auth_patcher.stop()

    @patch('backup_manager.run_backup', new_callable=AsyncMock)
    def test_backup_command_shrine(self, mock_run_backup):
        mock_run_backup.return_value = (True, "Backup Success")
        
        # Run the command directly (since it's a decorated function, we access the callback)
        # Note: app_commands.Command wraps the callback. 
        # In actual runtime, Discord calls callback. 
        # Here we call the function directly if it's accessible or via the tree if we can.
        # Since NyxOS.py doesn't expose the function easily without importing the decorated one,
        # we rely on importing it.
        
        # NyxOS.backup_command is the app_commands.Command object.
        # The callback is at NyxOS.backup_command.callback
        
        import asyncio
        asyncio.run(NyxOS.backup_command.callback(self.interaction, target="shrine"))
        
        # Verify call arguments
        mock_run_backup.assert_called_once()
        args, kwargs = mock_run_backup.call_args
        
        # target_id, output_name, target_type="channel", ...
        self.assertEqual(args[0], 300) # Shrine ID
        self.assertEqual(args[1], "Shrine")
        self.assertEqual(kwargs['target_type'], "channel")
        
    @patch('backup_manager.run_backup', new_callable=AsyncMock)
    def test_backup_command_temple(self, mock_run_backup):
        mock_run_backup.return_value = (True, "Backup Success")
        import asyncio
        asyncio.run(NyxOS.backup_command.callback(self.interaction, target="temple"))
        
        args, kwargs = mock_run_backup.call_args
        self.assertEqual(args[0], 100)
        self.assertEqual(args[1], "Temple")
        self.assertEqual(kwargs['target_type'], "guild")

if __name__ == '__main__':
    unittest.main()
