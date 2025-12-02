import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import backup_manager
import config

class TestBackupManager(unittest.TestCase):
    def setUp(self):
        config.BOT_TOKEN = "test_token"
        config.DROPBOX_APP_KEY = "test_key"
        config.DROPBOX_REFRESH_TOKEN = "test_refresh"

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.remove")
    def test_run_backup_command_construction_guild(self, mock_remove, mock_getsize, mock_exists, mock_makedirs, mock_subprocess):
        # Mock directory existence
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 # Fake size
        
        # Mock subprocess
        process_mock = MagicMock()
        process_mock.communicate = AsyncMock(return_value=(b"123 | General", b""))
        process_mock.wait = AsyncMock(return_value=None)
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock
        
        async def run_test():
             with patch("services.service.get_chat_response", new_callable=AsyncMock) as mock_llm:
                 mock_llm.return_value = "Test LLM Response"
                 with patch("dropbox.Dropbox"):
                    
                    # Run (Default type="guild")
                    await backup_manager.run_backup(123456789, "Test", target_type="guild")
                    
                    # First call should be channel list
                    args = mock_subprocess.call_args_list[0][0]
                    self.assertIn("channels", args)
                    self.assertIn("-g", args)
                    self.assertIn("123456789", args)

        asyncio.run(run_test())

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.remove")
    def test_run_backup_command_construction_channel(self, mock_remove, mock_getsize, mock_exists, mock_makedirs, mock_subprocess):
        # Mock directory existence
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 # Fake size
        
        # Mock subprocess
        process_mock = MagicMock()
        process_mock.communicate = AsyncMock(return_value=(b"", b""))
        process_mock.wait = AsyncMock(return_value=None)
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock
        
        async def run_test():
             with patch("services.service.get_chat_response", new_callable=AsyncMock) as mock_llm:
                 mock_llm.return_value = "Test LLM Response"
                 with patch("dropbox.Dropbox"):
                    
                    # Run with type="channel"
                    await backup_manager.run_backup(987654321, "TestChannel", target_type="channel")
                    
                    # First call should be export (skips list)
                    # args[0] is the executable path
                    args = mock_subprocess.call_args_list[0][0]
                    
                    # Should NOT be channels
                    self.assertNotIn("channels", args)
                    
                    # Should be export
                    self.assertIn("export", args)
                    self.assertIn("-c", args)
                    self.assertIn("987654321", args)

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
