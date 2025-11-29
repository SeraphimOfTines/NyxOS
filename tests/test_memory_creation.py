import unittest
import os
import shutil
import asyncio
import sys
import tempfile
from database import Database

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
# We must import memory_manager, but its 'db' is already initialized.
# We will swap it in setUp.
import memory_manager

class TestMemoryManager(unittest.IsolatedAsyncioTestCase):
    """
    Tests verification of memory_manager functions using the Database backend.
    Replaces the old file-based creation tests.
    """

    def setUp(self):
        # Create a temp database file
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp()
        os.close(self.temp_db_fd)
        
        # Initialize a new Database instance with this path
        self.test_db = Database(self.temp_db_path)
        
        # Inject this DB into memory_manager
        self.original_db = memory_manager.db
        memory_manager.db = self.test_db

    def tearDown(self):
        # Restore original DB
        memory_manager.db = self.original_db
        # Close and remove temp DB
        # self.test_db connection is closed when object is collected, but we should be safe
        if os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)

    async def test_write_context_buffer(self):
        """Test that write_context_buffer writes to the DB."""
        channel_id = "12345"
        channel_name = "creation-test"
        messages = [{"role": "user", "content": "Hello World"}]

        # Trigger write
        await memory_manager.write_context_buffer(messages, channel_id, channel_name)

        # Verify DB content
        stored = self.test_db.get_context_buffer(channel_id)
        self.assertIsNotNone(stored)
        self.assertIn("Hello World", stored)
        self.assertIn("MEMORY BUFFER FOR #creation-test", stored)

    async def test_write_response_append(self):
        """Test that appending a response works."""
        channel_id = "67890"
        channel_name = "append-test"
        response_text = "I am a bot"

        # Write initial (empty messages just to set up buffer headers?)
        # write_context_buffer with empty messages writes headers.
        await memory_manager.write_context_buffer([], channel_id, channel_name)
        
        # Append response
        await memory_manager.write_context_buffer([], channel_id, channel_name, append_response=response_text)

        stored = self.test_db.get_context_buffer(channel_id)
        self.assertIn("[ASSISTANT_REPLY]", stored)
        self.assertIn("I am a bot", stored)

    def test_clear_memory(self):
        """Test that clear_channel_memory clears the DB entry."""
        channel_id = "11111"
        channel_name = "clear-test"
        
        # Setup some memory
        # We can use the sync methods of DB directly to seed it, or use the async wrapper
        self.test_db.update_context_buffer(channel_id, channel_name, "Some Content")
        
        memory_manager.clear_channel_memory(channel_id, channel_name)

        stored = self.test_db.get_context_buffer(channel_id)
        self.assertIsNone(stored)

    def test_wipe_memories(self):
        """Test that wipe_all_memories clears all buffers."""
        self.test_db.update_context_buffer("1", "c1", "data")
        self.test_db.update_context_buffer("2", "c2", "data")
        
        memory_manager.wipe_all_memories()
        
        self.assertIsNone(self.test_db.get_context_buffer("1"))
        self.assertIsNone(self.test_db.get_context_buffer("2"))

if __name__ == '__main__':
    unittest.main()