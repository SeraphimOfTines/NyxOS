import unittest
import os
import shutil
import asyncio
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import memory_manager

class TestMemoryCreation(unittest.IsolatedAsyncioTestCase):
    """
    Tests specifically for verifying that memory_manager creates missing directories
    on demand, preventing FileNotFoundError.
    """

    def setUp(self):
        # Point to a temporary directory that we explicitly ensure DOES NOT exist at start
        self.base_test_dir = "tests/temp_creation_test"
        self.memory_dir = os.path.join(self.base_test_dir, "Memory")
        
        # Clean start
        if os.path.exists(self.base_test_dir):
            shutil.rmtree(self.base_test_dir)
            
        # Override config
        config.MEMORY_DIR = self.memory_dir

    def tearDown(self):
        if os.path.exists(self.base_test_dir):
            shutil.rmtree(self.base_test_dir)

    async def test_write_context_buffer_creates_directory(self):
        """Test that write_context_buffer creates the directory tree if missing."""
        channel_id = 12345
        channel_name = "creation-test"
        messages = [{"role": "user", "content": "Hello World"}]

        # 1. Verify directory is missing
        self.assertFalse(os.path.exists(self.memory_dir))

        # 2. Trigger write
        # We need to ensure an event loop is running for run_in_executor
        await memory_manager.write_context_buffer(messages, channel_id, channel_name)

        # 3. Verify directory and file exist
        expected_file = memory_manager.get_memory_filepath(channel_id, channel_name)
        
        self.assertTrue(os.path.exists(self.memory_dir), "Memory directory was not created")
        self.assertTrue(os.path.exists(expected_file), "Memory file was not created")
        
        with open(expected_file, 'r') as f:
            content = f.read()
            self.assertIn("Hello World", content)

    async def test_write_response_append_creates_directory(self):
        """Test that appending a response also creates the directory if missing."""
        channel_id = 67890
        channel_name = "append-test"
        response_text = "I am a bot"

        self.assertFalse(os.path.exists(self.memory_dir))

        await memory_manager.write_context_buffer([], channel_id, channel_name, append_response=response_text)

        expected_file = memory_manager.get_memory_filepath(channel_id, channel_name)
        
        self.assertTrue(os.path.exists(self.memory_dir))
        self.assertTrue(os.path.exists(expected_file))
        
        with open(expected_file, 'r') as f:
            content = f.read()
            self.assertIn("I am a bot", content)

    def test_clear_memory_creates_directory(self):
        """Test that clear_channel_memory creates the directory if missing."""
        channel_id = 11111
        channel_name = "clear-test"

        self.assertFalse(os.path.exists(self.memory_dir))

        memory_manager.clear_channel_memory(channel_id, channel_name)

        expected_file = memory_manager.get_memory_filepath(channel_id, channel_name)
        
        self.assertTrue(os.path.exists(self.memory_dir))
        self.assertTrue(os.path.exists(expected_file))
        
        with open(expected_file, 'r') as f:
            content = f.read()
            self.assertIn("MEMORY CLEARED", content)

    def test_wipe_memories_safety(self):
        """Test that wipe_all_memories does not crash if directory is missing."""
        self.assertFalse(os.path.exists(self.memory_dir))
        
        try:
            memory_manager.wipe_all_memories()
        except Exception as e:
            self.fail(f"wipe_all_memories raised exception on missing directory: {e}")

if __name__ == '__main__':
    unittest.main()
