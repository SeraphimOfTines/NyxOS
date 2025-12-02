import pytest
import os
import sqlite3
from database import Database

TEST_DB = "test_nuke.db"

@pytest.fixture
def db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    db_instance = Database(TEST_DB)
    yield db_instance
    
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_nuke_database(db):
    # 1. Add some data
    db.set_setting("test_key", "test_value")
    db.increment_user_score("123", "user")
    
    # Verify data exists
    assert db.get_setting("test_key") == "test_value"
    assert len(db.get_leaderboard()) == 1
    
    # 2. Nuke it
    success = db.nuke_database()
    assert success is True
    
    # 3. Verify data is gone
    assert db.get_setting("test_key") is None
    assert len(db.get_leaderboard()) == 0
    
    # 4. Verify structure is rebuilt (tables exist)
    # Trying to add data again should work
    db.set_setting("new_key", "new_value")
    assert db.get_setting("new_key") == "new_value"
