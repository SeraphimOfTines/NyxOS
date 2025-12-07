import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import backup_manager
import config

class TestBackupManagerTextOnly(unittest.TestCase):
    def setUp(self):
        config.BOT_TOKEN = "test_token"
        config.DROPBOX_APP_KEY = "test_key"
        config.DROPBOX_REFRESH_TOKEN = "test_refresh"

    @patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
    @patch("os.makedirs")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("os.remove")
    def test_run_backup_text_only(self, mock_remove, mock_getsize, mock_exists, mock_makedirs, mock_subprocess):
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
                    
                    # Run with type="channel" and text_only=True
                    await backup_manager.run_backup(987654321, "TestChannel", target_type="channel", text_only=True)
                    
                    # Inspect export command arguments
                    # The first call to subprocess is the export command (since channel mode skips listing)
                    args = mock_subprocess.call_args_list[0][0]
                    
                    # Verify Format
                    self.assertIn("PlainText", args)
                    self.assertNotIn("HtmlDark", args)
                    
                    # Verify Media Flags (Should be absent)
                    self.assertNotIn("--media", args)
                    self.assertNotIn("--reuse-media", args)
                    
                    # Verify Output Extension in arguments (Need to check the --output value)
                    # The --output argument follows the "--output" flag.
                    try:
                        output_idx = args.index("--output")
                        output_path = args[output_idx + 1]
                        self.assertTrue(output_path.endswith(".txt"), f"Output path should end with .txt, got {output_path}")
                    except ValueError:
                        self.fail("--output flag not found in command arguments")

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
