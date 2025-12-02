import unittest
import asyncio
from unittest.mock import patch, MagicMock
import backup_manager
import config

class TestBackupManager(unittest.TestCase):
    def setUp(self):
        config.BOT_TOKEN = "test_token"
        config.DROPBOX_APP_KEY = "test_key"
        config.DROPBOX_REFRESH_TOKEN = "test_refresh"

    @patch("asyncio.create_subprocess_exec")
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.remove")
    def test_run_backup_command_construction(self, mock_remove, mock_getsize, mock_exists, mock_makedirs, mock_subprocess):
        # Mock directory existence
        mock_exists.return_value = True
        mock_getsize.return_value = 1024 # Fake size
        
        # Mock subprocess
        process_mock = MagicMock()
        
        async def mock_readline():
            return b""
            
        async def mock_wait():
            return None
            
        process_mock.stdout.readline = mock_readline
        process_mock.wait = mock_wait
        process_mock.returncode = 0
        
        mock_subprocess.return_value = process_mock
        
        # Run the backup function (mocking the callback to avoid errors)
        async def run_test():
             # We expect it to fail at the upload stage because we aren't mocking dropbox fully,
             # or earlier if we don't mock enough. 
             # But we just want to check the subprocess call arguments.
             
             # We need to mock services.service.get_chat_response too or it will fail later
             with patch("services.service.get_chat_response", new_callable=MagicMock) as mock_llm:
                 mock_llm.return_value = "Test LLM Response"
                 # Also mock dropbox to avoid network calls or errors
                 with patch("dropbox.Dropbox"):
                    # Mock 7z subprocess too
                    with patch("asyncio.create_subprocess_exec") as mock_exec:
                        # Setup the mock for the first call (DiscordChatExporter) and second (7z)
                        proc_export = MagicMock()
                        proc_export.stdout.readline = mock_readline
                        proc_export.wait = mock_wait
                        proc_export.returncode = 0
                        
                        proc_7z = MagicMock()
                        proc_7z.wait = mock_wait
                        proc_7z.returncode = 0
                        
                        mock_exec.side_effect = [proc_export, proc_7z]
                        
                        await backup_manager.run_backup(123456789, "Test")
                        
                        # Check the first call to create_subprocess_exec (the export command)
                        args, _ = mock_exec.call_args_list[0]
                        
                        # Verify 'exportguild' is used
                        self.assertIn("exportguild", args)
                        self.assertIn("-g", args)
                        self.assertIn("123456789", args)

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
