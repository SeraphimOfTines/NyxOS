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
                
                # Enable WAL mode for better concurrency
                c.execute("PRAGMA journal_mode=WAL;")
                
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

                # View Persistence
                c.execute("""CREATE TABLE IF NOT EXISTS view_persistence (
                    message_id TEXT PRIMARY KEY,
                    data TEXT,
                    timestamp TIMESTAMP
                )""")
                
                # Active Bars (Status Stickers)
                c.execute("""CREATE TABLE IF NOT EXISTS active_bars (
                    channel_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    message_id TEXT,
                    user_id TEXT,
                    content TEXT,
                    original_prefix TEXT,
                    current_prefix TEXT,
                    is_sleeping INTEGER DEFAULT 0,
                    persisting INTEGER DEFAULT 0,
                    has_notification INTEGER DEFAULT 0,
                    previous_state TEXT,
                    timestamp TIMESTAMP
                )""")
                
                # Migration: Add current_prefix if missing
                try:
                    c.execute("ALTER TABLE active_bars ADD COLUMN current_prefix TEXT")
                except sqlite3.OperationalError:
                    pass # Column already exists

                # Migration: Add has_notification if missing
                try:
                    c.execute("ALTER TABLE active_bars ADD COLUMN has_notification INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass # Column already exists

                # Migration: Add checkmark_message_id if missing
                try:
                    c.execute("ALTER TABLE active_bars ADD COLUMN checkmark_message_id TEXT")
                except sqlite3.OperationalError:
                    pass # Column already exists
                
                # Bar History (For Restore)
                c.execute("""CREATE TABLE IF NOT EXISTS bar_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    content TEXT,
                    timestamp TIMESTAMP
                )""")

                # Master Bar (Single Source of Truth)
                c.execute("""CREATE TABLE IF NOT EXISTS master_bar (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    content TEXT
                )""")

                # Bar Whitelist
                c.execute("""CREATE TABLE IF NOT EXISTS bar_whitelist (
                    channel_id TEXT PRIMARY KEY
                )""")

                # Location Registry (Bar and Checkmark positions)
                c.execute("""CREATE TABLE IF NOT EXISTS location_registry (
                    channel_id TEXT PRIMARY KEY,
                    bar_msg_id TEXT,
                    check_msg_id TEXT,
                    timestamp TIMESTAMP
                )""")
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # --- Location Registry Methods ---

    def save_channel_location(self, channel_id, bar_msg_id=None, check_msg_id=None):
        """Upserts the location of the bar and checkmark for a channel."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # We need to handle partial updates. SQLite upsert replacing all values might wipe one if we pass None.
                # So we do a read-modify-write or use COALESCE if we could (but complexity).
                # Simplest: Read existing, update dict, write back.
                
                c.execute("SELECT bar_msg_id, check_msg_id FROM location_registry WHERE channel_id = ?", (str(channel_id),))
                row = c.fetchone()
                
                current_bar = row[0] if row else None
                current_check = row[1] if row else None
                
                new_bar = str(bar_msg_id) if bar_msg_id else current_bar
                new_check = str(check_msg_id) if check_msg_id else current_check
                
                c.execute("""
                    INSERT INTO location_registry (channel_id, bar_msg_id, check_msg_id, timestamp)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        bar_msg_id = excluded.bar_msg_id,
                        check_msg_id = excluded.check_msg_id,
                        timestamp = excluded.timestamp
                """, (str(channel_id), new_bar, new_check, datetime.now().isoformat(sep=' ')))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save channel location: {e}")

    def get_channel_location(self, channel_id):
        """Returns (bar_msg_id, check_msg_id) or (None, None)."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT bar_msg_id, check_msg_id FROM location_registry WHERE channel_id = ?", (str(channel_id),))
                row = c.fetchone()
                if row:
                    return (int(row[0]) if row[0] else None, int(row[1]) if row[1] else None)
                return (None, None)
        except Exception as e:
            logger.error(f"Failed to get channel location: {e}")
            return (None, None)

    def get_all_locations(self):
        """Returns dict {channel_id: {'bar': id, 'check': id}}."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT channel_id, bar_msg_id, check_msg_id FROM location_registry")
                rows = c.fetchall()
                data = {}
                for row in rows:
                    data[int(row[0])] = {
                        'bar': int(row[1]) if row[1] else None,
                        'check': int(row[2]) if row[2] else None
                    }
                return data
        except Exception as e:
            logger.error(f"Failed to get all locations: {e}")
            return {}

    # --- Master Bar & Whitelist Methods ---

    def set_master_bar(self, content):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO master_bar (id, content)
                    VALUES (1, ?)
                    ON CONFLICT(id) DO UPDATE SET content = excluded.content
                """, (content,))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set master bar: {e}")

    def get_master_bar(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT content FROM master_bar WHERE id = 1")
                row = c.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get master bar: {e}")
            return None

    def add_bar_whitelist(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO bar_whitelist (channel_id) VALUES (?)", (str(channel_id),))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to add to bar whitelist: {e}")

    def remove_bar_whitelist(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM bar_whitelist WHERE channel_id = ?", (str(channel_id),))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to remove from bar whitelist: {e}")

    def get_bar_whitelist(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT channel_id FROM bar_whitelist")
                return [row[0] for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get bar whitelist: {e}")
            return []

    # --- Active Bars Methods ---

    def save_bar(self, channel_id, guild_id, message_id, user_id, content, persisting, current_prefix=None, has_notification=False, checkmark_message_id=None):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # 1. Upsert Active Bar
                c.execute("""
                    INSERT INTO active_bars (channel_id, guild_id, message_id, user_id, content, persisting, current_prefix, has_notification, checkmark_message_id, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        message_id = excluded.message_id,
                        user_id = excluded.user_id,
                        content = excluded.content,
                        persisting = excluded.persisting,
                        current_prefix = excluded.current_prefix,
                        has_notification = excluded.has_notification,
                        checkmark_message_id = excluded.checkmark_message_id,
                        timestamp = excluded.timestamp
                """, (str(channel_id), str(guild_id), str(message_id), str(user_id), content, 1 if persisting else 0, current_prefix, 1 if has_notification else 0, str(checkmark_message_id) if checkmark_message_id else str(message_id), datetime.now().isoformat(sep=' ')))
                
                # 2. Check History
                # Get the most recent history entry for this channel
                c.execute("SELECT content FROM bar_history WHERE channel_id = ? ORDER BY id DESC LIMIT 1", (str(channel_id),))
                row = c.fetchone()
                last_content = row[0] if row else None
                
                # 3. Insert if new or different
                # We only save clean content changes.
                if content != last_content:
                    c.execute("INSERT INTO bar_history (channel_id, content, timestamp) VALUES (?, ?, ?)", 
                              (str(channel_id), content, datetime.now().isoformat(sep=' ')))

                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save bar: {e}")

    def set_bar_notification(self, channel_id, has_notification):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE active_bars SET has_notification = ? WHERE channel_id = ?", (1 if has_notification else 0, str(channel_id)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set bar notification: {e}")

    def get_latest_history(self, channel_id, offset=0):
        """Retrieves a bar content from history with offset (0 = latest, 1 = previous)."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT content FROM bar_history WHERE channel_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?", (str(channel_id), int(offset)))
                row = c.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get latest history: {e}")
            return None

    def get_bar(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT channel_id, guild_id, message_id, user_id, content, 
                           original_prefix, current_prefix, is_sleeping, persisting, 
                           has_notification, previous_state, timestamp, checkmark_message_id 
                    FROM active_bars WHERE channel_id = ?
                """, (str(channel_id),))
                row = c.fetchone()
                if row:
                    # Map row to dict
                    result = {
                        "channel_id": int(row[0]),
                        "guild_id": int(row[1]) if row[1] else None,
                        "message_id": int(row[2]),
                        "user_id": int(row[3]),
                        "content": row[4],
                        "original_prefix": row[5],
                        "current_prefix": row[6],
                        "is_sleeping": bool(row[7]),
                        "persisting": bool(row[8]),
                        "has_notification": bool(row[9]),
                        "previous_state": None,
                        "timestamp": row[11],
                        "checkmark_message_id": int(row[12]) if row[12] else int(row[2])
                    }
                    try:
                        if row[10]:
                             result["previous_state"] = json.loads(row[10])
                    except json.JSONDecodeError:
                         logger.warning(f"Corrupt JSON in active_bars for channel {row[0]}")
                    
                    return result
                return None
        except Exception as e:
            logger.error(f"Failed to get bar: {e}")
            return None

    def delete_bar(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM active_bars WHERE channel_id = ?", (str(channel_id),))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to delete bar: {e}")

    def get_all_bars(self):
        """
        Returns a dict {channel_id: {data...}} for all active bars.
        Includes robust error handling for corrupted data.
        """
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""SELECT 
                    channel_id, guild_id, message_id, user_id, content, 
                    persisting, current_prefix, has_notification, checkmark_message_id 
                    FROM active_bars""")
                rows = c.fetchall()
                
                data = {}
                corrupted_ids = []
                
                for row in rows:
                    try:
                        cid = int(row[0])
                        
                        # Safe conversion for other IDs
                        gid = int(row[1]) if row[1] and row[1].isdigit() else None
                        mid = int(row[2]) if row[2] and row[2].isdigit() else None
                        uid = int(row[3]) if row[3] and row[3].isdigit() else None
                        cmid = int(row[8]) if row[8] and row[8].isdigit() else mid

                        data[cid] = {
                            "guild_id": gid,
                            "message_id": mid,
                            "user_id": uid,
                            "content": row[4],
                            "persisting": bool(row[5]),
                            "current_prefix": row[6],
                            "has_notification": bool(row[7]),
                            "checkmark_message_id": cmid
                        }
                    except ValueError as ve:
                        # This catches the 'invalid literal for int()'
                        logger.warning(f"⚠️ skipped corrupted bar record {row[0]}: {ve}")
                        corrupted_ids.append(row[0])
                        continue
                
                # Auto-Clean corrupted entries
                if corrupted_ids:
                    logger.info(f"🧹 Cleaning {len(corrupted_ids)} corrupted entries from active_bars...")
                    for bad_id in corrupted_ids:
                        try:
                            c.execute("DELETE FROM active_bars WHERE channel_id = ?", (bad_id,))
                        except: pass
                    conn.commit()
                    
                return data
        except Exception as e:
            logger.error(f"Failed to get all bars: {e}")
            return {}

    def fix_corrupted_db(self):
        """Sanitizes the database by removing rows with non-integer IDs."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # Find bad rows using SQL logic if possible, or just fetch/clean like above.
                # Simple approach: Delete where channel_id is not an integer
                # SQLite 'GLOB' or 'LIKE' or regex is tricky.
                # We'll rely on the auto-clean inside get_all_bars() which is called on startup.
                # But we can also clean whitelist.
                
                c.execute("SELECT channel_id FROM bar_whitelist")
                rows = c.fetchall()
                bad_wl = []
                for row in rows:
                    if not str(row[0]).isdigit():
                        bad_wl.append(row[0])
                
                for bad in bad_wl:
                     logger.info(f"🧹 Removing corrupted whitelist entry: {bad}")
                     c.execute("DELETE FROM bar_whitelist WHERE channel_id = ?", (bad,))
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to run DB fix: {e}")

    def update_bar_content(self, channel_id, content):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE active_bars SET content = ? WHERE channel_id = ?", (content, str(channel_id)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update bar content: {e}")

    def update_bar_message_id(self, channel_id, message_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE active_bars SET message_id = ? WHERE channel_id = ?", (str(message_id), str(channel_id)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update bar message_id: {e}")

    def set_bar_sleeping(self, channel_id, is_sleeping, original_prefix=None):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                if is_sleeping:
                    c.execute("UPDATE active_bars SET is_sleeping = 1, original_prefix = ? WHERE channel_id = ?", (original_prefix, str(channel_id)))
                else:
                    c.execute("UPDATE active_bars SET is_sleeping = 0 WHERE channel_id = ?", (str(channel_id),))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to set bar sleeping: {e}")

    def save_previous_state(self, channel_id, state):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                json_state = json.dumps(state)
                c.execute("UPDATE active_bars SET previous_state = ? WHERE channel_id = ?", (json_state, str(channel_id)))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save previous state: {e}")

    def get_previous_state(self, channel_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT previous_state FROM active_bars WHERE channel_id = ?", (str(channel_id),))
                row = c.fetchone()
                if row and row[0]:
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt JSON previous_state for channel {channel_id}")
                        return None
                return None
        except Exception as e:
            logger.error(f"Failed to get previous state: {e}")
            return None

    # --- View Persistence Methods ---

    def save_view_state(self, message_id, data):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # Serialize complex objects if needed (but data passed should be dict of primitives)
                json_data = json.dumps(data)
                c.execute("""
                    INSERT INTO view_persistence (message_id, data, timestamp)
                    VALUES (?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        data = excluded.data,
                        timestamp = excluded.timestamp
                """, (str(message_id), json_data, datetime.now().isoformat(sep=' ')))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save view state: {e}")

    def get_view_state(self, message_id):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT data FROM view_persistence WHERE message_id = ?", (str(message_id),))
                row = c.fetchone()
                if row:
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupt JSON view_state for message {message_id}")
                        return None
                return None
        except Exception as e:
            logger.error(f"Failed to get view state: {e}")
            return None

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
                """, (str(channel_id), channel_name, content, datetime.now().isoformat(sep=' ')))
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
                """, (new_content, datetime.now().isoformat(sep=' '), str(channel_id)))
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

    def clear_user_scores(self):
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM user_scores")
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to clear user scores: {e}")
            return False

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
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                         logger.warning(f"Corrupt JSON in server_settings for key {key}")
                         return default
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

    # --- Maintenance Methods ---

    def nuke_database(self):
        """
        NUCLEAR OPTION: Drops ALL tables and re-initializes the database.
        Use only in case of severe corruption or when a hard reset is required.
        """
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # Get all table names
                c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = c.fetchall()
                
                # Drop each table
                for table in tables:
                    table_name = table[0]
                    # sqlite_sequence is internal, usually don't drop it manually but for a nuke... 
                    # Dropping tables with AUTOINCREMENT usually handles it, but let's be safe and skip internal ones if needed.
                    # Actually, dropping everything is fine, init_db will recreate.
                    if table_name != "sqlite_sequence":
                        c.execute(f"DROP TABLE IF EXISTS {table_name}")
                
                # If we want to be thorough about autoincrement counters:
                c.execute("DELETE FROM sqlite_sequence")
                
                conn.commit()
            
            logger.warning("⚠️ DATABASE NUKED! All tables dropped. Re-initializing...")
            self._init_db()
            return True
        except Exception as e:
            logger.error(f"Failed to nuke database: {e}")
            return False
