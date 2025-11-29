import unittest
import os
import json
import tempfile
from database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        self.db = Database(self.temp_db.name)

    def tearDown(self):
        os.unlink(self.temp_db.name)

    def test_context_buffer(self):
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
        lb = self.db.get_leaderboard()
        self.assertEqual(len(lb), 1)
        self.assertEqual(lb[0]['username'], username)
        self.assertEqual(lb[0]['count'], 2)

    def test_suppressed_users(self):
        user_id = "555"
        
        # Test Toggle On
        is_suppressed = self.db.toggle_suppressed_user(user_id)
        self.assertTrue(is_suppressed)
        users = self.db.get_suppressed_users()
        self.assertIn(user_id, users)
        
        # Test Toggle Off
        is_suppressed = self.db.toggle_suppressed_user(user_id)
        self.assertFalse(is_suppressed)
        users = self.db.get_suppressed_users()
        self.assertNotIn(user_id, users)

    def test_server_settings(self):
        key = "test_setting"
        val = {"foo": "bar"}
        
        # Test Set/Get
        self.db.set_setting(key, val)
        stored = self.db.get_setting(key)
        self.assertEqual(stored, val)
        
        # Test Default
        self.assertEqual(self.db.get_setting("nonexistent", "default"), "default")

    def test_sanitization_storage(self):
        # Verify that the DB stores exactly what it is given, brackets and all.
        # This ensures that if we sanitize BEFORE, the DB doesn't mangle it,
        # and if we have structural brackets, they are preserved.
        channel_id = "safe_check"
        content_with_brackets = "[ROLE]\nContent with (parentheses) and [brackets]"
        
        self.db.update_context_buffer(channel_id, "safe_chan", content_with_brackets)
        stored = self.db.get_context_buffer(channel_id)
        self.assertEqual(stored, content_with_brackets)

if __name__ == '__main__':
    unittest.main()
