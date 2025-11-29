import unittest
import sys
import os
import json
import sqlite3

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import Database

class MockDatabase(Database):
    """Subclass to force a persistent in-memory connection for testing."""
    def __init__(self):
        self.persistent_conn = sqlite3.connect(":memory:")
        super().__init__(":memory:")

    def _get_conn(self):
        # Return the same connection every time so data persists in memory
        return self.persistent_conn

    def close(self):
        self.persistent_conn.close()

class TestDatabase(unittest.TestCase):

    def setUp(self):
        """Create a new in-memory database for each test."""
        self.db = MockDatabase()

    def tearDown(self):
        """Close the persistent connection."""
        self.db.close()

    # --- test_init_db ---
    def test_init_db(self):
        """Ensure all tables are created."""
        with self.db._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in c.fetchall()}
            
        expected_tables = {
            "active_bars", 
            "user_scores", 
            "context_buffers", 
            "suppressed_users", 
            "server_settings", 
            "view_persistence",
            "bar_history"
        }
        self.assertTrue(expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}")

    # --- test_active_bars_crud ---
    def test_active_bars_crud(self):
        """Create, Retrieve, Update, Delete active bars."""
        # 1. Create (Save)
        self.db.save_bar(
            channel_id="123", 
            guild_id="456", 
            message_id="789", 
            user_id="111", 
            content="Status Bar", 
            persisting=True
        )
        
        # 2. Retrieve
        bar = self.db.get_bar("123")
        self.assertIsNotNone(bar)
        self.assertEqual(bar['content'], "Status Bar")
        self.assertTrue(bar['persisting'])
        self.assertEqual(bar['message_id'], 789) # Should be int

        # 3. Update (Upsert)
        self.db.save_bar(
            channel_id="123", 
            guild_id="456", 
            message_id="999", # Changed Message ID
            user_id="111", 
            content="Updated Bar", # Changed Content
            persisting=False # Changed Persistence
        )
        
        bar_updated = self.db.get_bar("123")
        self.assertEqual(bar_updated['content'], "Updated Bar")
        self.assertEqual(bar_updated['message_id'], 999)
        self.assertFalse(bar_updated['persisting'])

        # 4. Delete
        self.db.delete_bar("123")
        self.assertIsNone(self.db.get_bar("123"))

    # --- test_bar_history ---
    def test_bar_history(self):
        """Verify history recording and duplicate prevention."""
        cid = "hist_chan"
        
        # 1. Save Initial
        self.db.save_bar(cid, "g", "m1", "u", "Content A", True)
        
        # Check history (should be 1 entry: Content A)
        hist1 = self.db.get_latest_history(cid)
        self.assertEqual(hist1, "Content A")
        
        # 2. Update with SAME content
        self.db.save_bar(cid, "g", "m2", "u", "Content A", True)
        
        # Check history count manually to ensure no duplicate
        with self.db._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM bar_history WHERE channel_id = ?", (cid,))
            count = c.fetchone()[0]
        self.assertEqual(count, 1, "Should not add history if content is identical")

        # 3. Update with DIFFERENT content
        self.db.save_bar(cid, "g", "m3", "u", "Content B", True)
        
        # Check latest
        latest = self.db.get_latest_history(cid, offset=0)
        self.assertEqual(latest, "Content B")
        
        # Check previous
        prev = self.db.get_latest_history(cid, offset=1)
        self.assertEqual(prev, "Content A")

    # --- test_context_buffers ---
    def test_context_buffers(self):
        """Test update (overwrite) and append operations."""
        cid = "ctx_chan"
        
        # 1. Update (Overwrite)
        self.db.update_context_buffer(cid, "General", "Start")
        self.assertEqual(self.db.get_context_buffer(cid), "Start")
        
        # 2. Append
        self.db.append_to_context_buffer(cid, " End")
        self.assertEqual(self.db.get_context_buffer(cid), "Start End")
        
        # 3. Update Again (Overwrite)
        self.db.update_context_buffer(cid, "General", "New Start")
        self.assertEqual(self.db.get_context_buffer(cid), "New Start")

    # --- test_user_scores ---
    def test_user_scores(self):
        """Test increment logic and leaderboard sorting."""
        # 1. Increment New User
        count = self.db.increment_user_score("u1", "UserOne")
        self.assertEqual(count, 1)
        
        # 2. Increment Existing
        count = self.db.increment_user_score("u1", "UserOne")
        self.assertEqual(count, 2)
        
        # 3. Add another user
        self.db.increment_user_score("u2", "UserTwo") # 1
        
        # 4. Leaderboard
        lb = self.db.get_leaderboard()
        # Expected: UserOne (2), UserTwo (1)
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0]['user_id'], "u1")
        self.assertEqual(lb[0]['count'], 2)
        self.assertEqual(lb[1]['user_id'], "u2")
        self.assertEqual(lb[1]['count'], 1)

    # --- test_server_settings ---
    def test_server_settings(self):
        """Test saving/retrieving complex JSON objects."""
        # List
        self.db.set_setting("test_list", [1, 2, 3])
        val_list = self.db.get_setting("test_list")
        self.assertEqual(val_list, [1, 2, 3])
        
        # Dict
        complex_data = {"enabled": True, "nested": {"a": 1}}
        self.db.set_setting("test_dict", complex_data)
        val_dict = self.db.get_setting("test_dict")
        self.assertEqual(val_dict, complex_data)
        
        # Missing Key
        self.assertIsNone(self.db.get_setting("missing_key"))
        self.assertEqual(self.db.get_setting("missing_key", "default"), "default")

if __name__ == '__main__':
    unittest.main()