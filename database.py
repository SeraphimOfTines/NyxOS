import sqlite3
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("Database")

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        # 30s timeout to wait for locks to clear in high concurrency
        return sqlite3.connect(self.db_path, timeout=30.0)

    def _init_db(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                
                # Context Buffer (One per channel)
                # Stores the formatted text representation of the context window
                c.execute("""CREATE TABLE IF NOT EXISTS context_buffers (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT,
                    content TEXT,
                    last_updated TIMESTAMP
                )""")
                
                # User Scores (Good Bot)
                c.execute("""CREATE TABLE IF NOT EXISTS user_scores (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    count INTEGER DEFAULT 0
                )""")
                
                # Suppressed Users
                c.execute("""CREATE TABLE IF NOT EXISTS suppressed_users (
                    user_id TEXT PRIMARY KEY
                )""")
                
                # Server Settings
                c.execute("""CREATE TABLE IF NOT EXISTS server_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )""")
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # --- Context Buffer Methods ---

    def update_context_buffer(self, channel_id, channel_name, content):
        """Replaces the context buffer for a channel."""
        # Sanitize: Ensure no extra brackets if they somehow slipped through (though caller should handle)
        # content = content.replace('[', '(').replace(']', ')') 
        # NOTE: Caller (memory_manager) constructs the content. We assume it's ready to store but we can be safe.
        # However, user said "sanitize them in the database". 
        # If this is the formatted string, replacing [ with ( might break [ASSISTANT_REPLY] or headers.
        # The Headers like [ROLE] are needed. 
        # The user likely means "sanitize user content".
        # I will leave global replacement out of here to avoid breaking the format structure ([ROLE]).
        
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO context_buffers (channel_id, channel_name, content, last_updated)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        channel_name = excluded.channel_name,
                        content = excluded.content,
                        last_updated = excluded.last_updated
                """, (str(channel_id), channel_name, content, datetime.now()))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update context buffer: {e}")

    def append_to_context_buffer(self, channel_id, content):
        """Appends text to the existing buffer."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # Get current content
                c.execute("SELECT content FROM context_buffers WHERE channel_id = ?", (str(channel_id),))
                row = c.fetchone()
                current_content = row[0] if row else ""
                
                new_content = current_content + content
                
                c.execute("""
                    UPDATE context_buffers 
                    SET content = ?, last_updated = ?
                    WHERE channel_id = ?
                """, (new_content, datetime.now(), str(channel_id)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to append context buffer: {e}")

    def get_context_buffer(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT content FROM context_buffers WHERE channel_id = ?", (str(channel_id),))
                row = c.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get context buffer: {e}")
            return None
            
    def clear_context_buffer(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM context_buffers WHERE channel_id = ?", (str(channel_id),))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to clear context buffer: {e}")

    def wipe_all_buffers(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM context_buffers")
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to wipe all buffers: {e}")

    # --- Good Bot Methods ---

    def increment_user_score(self, user_id, username):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # Upsert logic
                c.execute("""
                    INSERT INTO user_scores (user_id, username, count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET
                        count = count + 1,
                        username = excluded.username
                """, (str(user_id), username))
                
                # Return new count
                c.execute("SELECT count FROM user_scores WHERE user_id = ?", (str(user_id),))
                return c.fetchone()[0]
        except Exception as e:
            logger.error(f"Failed to increment user score: {e}")
            return 0

    def get_leaderboard(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id, username, count FROM user_scores ORDER BY count DESC")
                rows = c.fetchall()
                return [{"user_id": r[0], "username": r[1], "count": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []

    # --- Suppressed Users Methods ---

    def get_suppressed_users(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id FROM suppressed_users")
                return {row[0] for row in c.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get suppressed users: {e}")
            return set()

    def toggle_suppressed_user(self, user_id):
        uid_str = str(user_id)
        is_suppressed = False
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT 1 FROM suppressed_users WHERE user_id = ?", (uid_str,))
                exists = c.fetchone()
                
                if exists:
                    c.execute("DELETE FROM suppressed_users WHERE user_id = ?", (uid_str,))
                    is_suppressed = False
                else:
                    c.execute("INSERT INTO suppressed_users (user_id) VALUES (?)", (uid_str,))
                    is_suppressed = True
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to toggle suppressed user: {e}")
            
        return is_suppressed

    # --- Server Settings Methods ---

    def get_setting(self, key, default=None):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT value FROM server_settings WHERE key = ?", (str(key),))
                row = c.fetchone()
                if row:
                    return json.loads(row[0])
                return default
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default

    def set_setting(self, key, value):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                json_val = json.dumps(value)
                c.execute("""
                    INSERT INTO server_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (str(key), json_val))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
