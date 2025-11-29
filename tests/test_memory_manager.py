import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import os
import asyncio
import datetime

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memory_manager
import config

class TestMemoryManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Patch the 'db' instance in memory_manager
        self.db_patcher = patch('memory_manager.db')
        self.mock_db = self.db_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()

    # --- test_write_context_buffer ---
    async def test_write_context_buffer(self):
        """
        Verify message list is formatted correctly into a string.
        Check that [images] are noted.
        Ensure brackets in user content are sanitized ([ -> ().
        """
        # Mock Data
        messages = [
            {"role": "system", "content": "System Prompt"},
            {"role": "user", "content": "User with [brackets]"},
            {"role": "user", "content": [
                {"type": "text", "text": "Image Prompt"},
                {"type": "image_url", "image_url": "http://fake.com/img.png"}
            ]},
            {"role": "assistant", "content": "I am <search_results>Hidden</search_results> here."}
        ]
        channel_id = "123"
        channel_name = "test-chan"

        # Execute
        await memory_manager.write_context_buffer(messages, channel_id, channel_name)

        # Verify
        # Argument 2 passed to db.update_context_buffer is the 'content' string
        self.assertTrue(self.mock_db.update_context_buffer.called)
        call_args = self.mock_db.update_context_buffer.call_args
        content_arg = call_args[0][2] # (channel_id, channel_name, content)

        # Assertions on the formatted string
        self.assertIn("[SYSTEM]\nSystem Prompt", content_arg)
        # Check Bracket Sanitization
        self.assertIn("User with (brackets)", content_arg) 
        self.assertNotIn("User with [brackets]", content_arg)
        # Check Image Note
        self.assertIn("(IMAGE DATA SENT TO AI)", content_arg)
        # Check Search Result Omission
        self.assertIn("(WEB SEARCH RESULTS OMITTED FROM LOG)", content_arg)
        self.assertNotIn("<search_results>", content_arg)

    async def test_write_context_buffer_append(self):
        """Verify append_response logic."""
        resp = "New [Response]"
        await memory_manager.write_context_buffer(None, "123", "name", append_response=resp)
        
        self.assertTrue(self.mock_db.append_to_context_buffer.called)
        call_args = self.mock_db.append_to_context_buffer.call_args
        content_arg = call_args[0][1] # (channel_id, content)
        
        self.assertIn("[ASSISTANT_REPLY]", content_arg)
        self.assertIn("New (Response)", content_arg) # Sanitized

    # --- test_log_conversation ---
    def test_log_conversation(self):
        """
        Mock file I/O. Verify it writes to the correct date-stamped folder/file.
        Verify log format timestamping.
        """
        channel_name = "general"
        user_name = "Seraph"
        user_id = "999"
        content = "Hello World"
        
        # Mock datetime to have a fixed date for path verification
        fixed_date = datetime.datetime(2025, 11, 29, 12, 0, 0)
        
        with patch('memory_manager.datetime') as mock_dt, \
             patch('os.makedirs') as mock_makedirs, \
             patch('os.path.exists', return_value=True), \
             patch('builtins.open', mock_open()) as mock_file:
            
            mock_dt.now.return_value = fixed_date
            mock_dt.strftime = datetime.datetime.strftime # Keep strftime working

            memory_manager.log_conversation(channel_name, user_name, user_id, content)

            # Verify Path
            # Use config.LOGS_DIR to match the actual code's path resolution
            expected_dir = os.path.join(config.LOGS_DIR, "2025-11-29")
            mock_makedirs.assert_called_with(expected_dir, exist_ok=True)
            
            # Verify Write
            handle = mock_file()
            handle.write.assert_called()
            written_content = handle.write.call_args[0][0]
            
            self.assertIn("[12:00:00]", written_content)
            self.assertIn("Seraph [999]: Hello World", written_content)
if __name__ == '__main__':
    unittest.main()