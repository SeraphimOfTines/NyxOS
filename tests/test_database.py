import unittest
import json
import time
from database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Use in-memory database for speed and isolation
        # We must persist the connection for :memory: or it wipes on every close
        import sqlite3
        from contextlib import contextmanager

        class MemoryDatabase(Database):
            def __init__(self):
                self.db_path = ":memory:"
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._init_db()

            def _get_conn(self):
                @contextmanager
                def no_close():
                    yield self.conn
                return no_close()

        self.db = MemoryDatabase()

    def test_init_db(self):
        # Verify tables exist
        with self.db._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in c.fetchall()]
            self.assertIn("active_bars", tables)
            self.assertIn("user_scores", tables)
            self.assertIn("context_buffers", tables)
            self.assertIn("bar_history", tables)
            self.assertIn("server_settings", tables)

    def test_active_bars_crud(self):
        channel_id = "123"
        guild_id = "456"
        message_id = "789"
        user_id = "000"
        content = "Test Bar Content"
        persisting = True

        # 1. Create (Save)
        self.db.save_bar(channel_id, guild_id, message_id, user_id, content, persisting)
        
        # 2. Retrieve
        bar = self.db.get_bar(channel_id)
        self.assertIsNotNone(bar)
        self.assertEqual(bar['channel_id'], int(channel_id))
        self.assertEqual(bar['content'], content)
        self.assertTrue(bar['persisting'])

        # 3. Update (Upsert)
        new_content = "Updated Content"
        new_message_id = "790"
        self.db.save_bar(channel_id, guild_id, new_message_id, user_id, new_content, False)
        
        bar = self.db.get_bar(channel_id)
        self.assertEqual(bar['content'], new_content)
        self.assertEqual(bar['message_id'], int(new_message_id))
        self.assertFalse(bar['persisting'])

        # 4. Delete
        self.db.delete_bar(channel_id)
        bar = self.db.get_bar(channel_id)
        self.assertIsNone(bar)

    def test_bar_history(self):
        channel_id = "history_test"
        
        # 1. Save initial
        self.db.save_bar(channel_id, "g", "m1", "u", "Content 1", True)
        
        # Verify history recorded
        history = self.db.get_latest_history(channel_id)
        self.assertEqual(history, "Content 1")
        
        # 2. Save same content (should NOT create new history entry)
        # We'll wait a split second to ensure timestamp would differ if it inserted
        # but we check content count logic indirectly or just rely on get_latest_history
        self.db.save_bar(channel_id, "g", "m2", "u", "Content 1", True)
        
        # 3. Save different content
        self.db.save_bar(channel_id, "g", "m3", "u", "Content 2", True)
        
        latest = self.db.get_latest_history(channel_id, offset=0)
        previous = self.db.get_latest_history(channel_id, offset=1)
        
        self.assertEqual(latest, "Content 2")
        self.assertEqual(previous, "Content 1")

    def test_context_buffers(self):
        channel_id = "123"
        content = "[SYSTEM]\nHello"
        
        # Test Insert
        self.db.update_context_buffer(channel_id, "test_chan", content)
        stored = self.db.get_context_buffer(channel_id)
        self.assertEqual(stored, content)
        
        # Test Update (Overwrite)
        new_content = "[SYSTEM]\nNew"
        self.db.update_context_buffer(channel_id, "test_chan", new_content)
        stored = self.db.get_context_buffer(channel_id)
        self.assertEqual(stored, new_content)
        
        # Test Append
        append_content = "\n[USER]\nHi"
        self.db.append_to_context_buffer(channel_id, append_content)
        stored = self.db.get_context_buffer(channel_id)
        self.assertEqual(stored, new_content + append_content)
        
        # Test Clear
        self.db.clear_context_buffer(channel_id)
        self.assertIsNone(self.db.get_context_buffer(channel_id))

    def test_user_scores(self):
        user_id = "999"
        username = "Tester"
        
        # Test Increment New
        count = self.db.increment_user_score(user_id, username)
        self.assertEqual(count, 1)
        
        # Test Increment Existing
        count = self.db.increment_user_score(user_id, username)
        self.assertEqual(count, 2)
        
        # Test Leaderboard
        # Add another user
        self.db.increment_user_score("888", "User2")
        
        lb = self.db.get_leaderboard()
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0]['username'], username) # Tester (2)
        self.assertEqual(lb[1]['username'], "User2") # User2 (1)

    def test_server_settings(self):
        key = "complex_setting"
        val = {"list": [1, 2, 3], "dict": {"a": "b"}}
        
        # Test Set/Get
        self.db.set_setting(key, val)
        stored = self.db.get_setting(key)
        self.assertEqual(stored, val)
        
        # Test Default
        self.assertEqual(self.db.get_setting("nonexistent", "default"), "default")

if __name__ == '__main__':
    unittest.main()