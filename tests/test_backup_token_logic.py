import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import backup_manager
import config
import asyncio
import os

class TestBackupTokenLogic(unittest.TestCase):
    def setUp(self):
        self.original_bot_token = config.BOT_TOKEN
        self.original_backup_token = config.BACKUP_TOKEN
        
        config.BOT_TOKEN = "bot_token_123"
        config.BACKUP_TOKEN = None

    def tearDown(self):
        config.BOT_TOKEN = self.original_bot_token
        config.BACKUP_TOKEN = self.original_backup_token

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.remove")
    @patch("os.path.getsize")
    def test_uses_bot_token_when_backup_token_missing(self, mock_getsize, mock_remove, mock_exists, mock_makedirs, mock_exec):
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        
        # Mock subprocess process object
        proc = MagicMock()
        # communicate must be an async method
        proc.communicate = AsyncMock(return_value=(b"123 | General", b""))
        proc.returncode = 0
        # Mock wait for the zip process (second call)
        proc.wait = AsyncMock(return_value=None)
        
        # The mock_exec (create_subprocess_exec) is an AsyncMock, so awaiting it returns its return_value.
        # We set the return_value to be our process mock.
        mock_exec.return_value = proc
        
        # Run backup
        asyncio.run(backup_manager.run_backup(123, "Test"))
        
        # Verify env used in subprocess
        # mock_exec is called. args/kwargs are captured.
        call_kwargs = mock_exec.call_args_list[0][1] # First call (channels)
        env = call_kwargs.get("env")
        self.assertEqual(env["DISCORD_TOKEN"], "bot_token_123")

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.remove")
    @patch("os.path.getsize")
    def test_uses_backup_token_when_present(self, mock_getsize, mock_remove, mock_exists, mock_makedirs, mock_exec):
        config.BACKUP_TOKEN = "user_token_456"
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        
        # Mock subprocess
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"123 | General", b""))
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=None)
        mock_exec.return_value = proc
        
        # Run backup
        asyncio.run(backup_manager.run_backup(123, "Test"))
        
        # Verify env used in subprocess
        call_kwargs = mock_exec.call_args_list[0][1] # First call (channels)
        env = call_kwargs.get("env")
        self.assertEqual(env["DISCORD_TOKEN"], "user_token_456")

if __name__ == "__main__":
    unittest.main()