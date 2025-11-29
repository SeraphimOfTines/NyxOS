import os
import json
from datetime import datetime
import re
import config
import shutil
import logging
import asyncio
from functools import partial
from database import Database

logger = logging.getLogger("MemoryManager")

# Initialize Database
# This replaces the file-based storage for context buffers, scores, settings, etc.
db = Database(config.DATABASE_FILE)

def wipe_all_memories():
    """Deletes all memory buffers from the database."""
    try:
        db.wipe_all_buffers()
        logger.info("Wiped all memory buffers from database.")
    except Exception as e:
        logger.error(f"Failed to wipe all memories: {e}")

def wipe_all_logs():
    import os
    import config
    try:
        import shutil
        if os.path.exists(config.LOGS_DIR):
            shutil.rmtree(config.LOGS_DIR)
            os.makedirs(config.LOGS_DIR)
    except Exception as e:
        print(f"Failed to wipe logs: {e}")

# --- Active Bars (DB Facade) ---

def save_bar(channel_id, guild_id, message_id, user_id, content, persisting):
    db.save_bar(channel_id, guild_id, message_id, user_id, content, persisting)

def get_bar(channel_id):
    return db.get_bar(channel_id)

def delete_bar(channel_id):
    db.delete_bar(channel_id)

def get_all_bars():
    return db.get_all_bars()

def update_bar_content(channel_id, content):
    db.update_bar_content(channel_id, content)

def update_bar_message_id(channel_id, message_id):
    db.update_bar_message_id(channel_id, message_id)

def set_bar_sleeping(channel_id, is_sleeping, original_prefix=None):
    db.set_bar_sleeping(channel_id, is_sleeping, original_prefix)

def save_previous_state(channel_id, state):
    db.save_previous_state(channel_id, state)

def get_previous_state(channel_id):
    return db.get_previous_state(channel_id)

def get_bar_history(channel_id, offset=0):
    return db.get_latest_history(channel_id, offset)

def log_conversation(channel_name, user_name, user_id, content):
    """Writes to the human-readable daily logs (kept as files)."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily_log_dir = os.path.join(config.LOGS_DIR, today)
    os.makedirs(daily_log_dir, exist_ok=True)
    
    safe_channel = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
    log_file = os.path.join(daily_log_dir, f"{safe_channel}.log")
    
    try:
        if not os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== LOG STARTED: {today} ===\nSYSTEM PROMPT:\n{config.SYSTEM_PROMPT_TEMPLATE}\n====================================\n\n")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {user_name} [{user_id}]: {content}\n")
    except Exception as e:
        logger.error(f"Failed to write to log: {e}")

async def write_context_buffer(messages, channel_id, channel_name, append_response=None):
    """
    Writes the current context window to the database for debugging/inspection.
    Uses DB instead of files now.
    """
    loop = asyncio.get_running_loop()

    try:
        if append_response:
            # Sanitize response before storing
            clean_resp = append_response.replace('[', '(').replace(']', ')')
            content = f"[ASSISTANT_REPLY]\n{clean_resp}\n\n"
            # Run DB update in executor to avoid blocking the event loop
            await loop.run_in_executor(None, db.append_to_context_buffer, channel_id, content)
            return
            
        # Build content string in memory
        buffer = []
        buffer.append(f"=== MEMORY BUFFER FOR #{channel_name} ({channel_id}) ===\n")
        buffer.append(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        buffer.append("=====================================================\n\n")
        
        for msg in messages:
            role = msg['role'].upper()
            content = msg['content']
            
            if isinstance(content, list):
                text_parts = []
                has_image = False
                for item in content:
                    if item['type'] == 'text': text_parts.append(item['text'])
                    elif item['type'] == 'image_url': has_image = True
                content = " ".join(text_parts)
                if has_image: content += " (IMAGE DATA SENT TO AI)"
            
            if isinstance(content, str):
                if "<search_results>" in content:
                    content = re.sub(r'<search_results>.*?</search_results>', '(WEB SEARCH RESULTS OMITTED FROM LOG)', content, flags=re.DOTALL)
                # Sanitize brackets in user content to prevent formatting injection
                content = content.replace('[', '(').replace(']', ')')

            buffer.append(f"[{role}]\n{content}\n\n")
        
        full_content = "".join(buffer)
        await loop.run_in_executor(None, db.update_context_buffer, channel_id, channel_name, full_content)

    except Exception as e:
        logger.error(f"Failed to write memory buffer to DB: {e}")

def clear_channel_memory(channel_id, channel_name):
    """Clears the context buffer for a channel in the database."""
    try:
        db.clear_context_buffer(channel_id)
    except Exception as e:
        logger.error(f"Failed to clear memory buffer: {e}")

# --- GOOD BOT LOGIC ---

def increment_good_bot(user_id, username):
    return db.increment_user_score(user_id, username)

def get_good_bot_leaderboard():
    return db.get_leaderboard()

# --- EMBED SUPPRESSION LOGIC ---

def get_suppressed_users():
    return db.get_suppressed_users()

def toggle_suppressed_user(user_id):
    return db.toggle_suppressed_user(user_id)

# --- SERVER SETTINGS ---

def get_server_setting(key, default=True):
    return db.get_setting(key, default)

def set_server_setting(key, value):
    db.set_setting(key, value)

# --- VIEW PERSISTENCE ---

def save_view_state(message_id, data):
    db.save_view_state(message_id, data)

def get_view_state(message_id):
    return db.get_view_state(message_id)

# --- ALLOWED CHANNELS ---

# Cache for allowed channels to avoid DB hits on every message
_ALLOWED_CHANNELS_CACHE = None

def get_allowed_channels():
    """Returns the list of allowed channel IDs, using a memory cache."""
    global _ALLOWED_CHANNELS_CACHE
    if _ALLOWED_CHANNELS_CACHE is None:
        _ALLOWED_CHANNELS_CACHE = get_server_setting("allowed_channels", [])
    return _ALLOWED_CHANNELS_CACHE

def add_allowed_channel(channel_id):
    """Adds a channel ID to the allowed list."""
    global _ALLOWED_CHANNELS_CACHE
    channels = get_allowed_channels()
    if channel_id not in channels:
        channels.append(channel_id)
        set_server_setting("allowed_channels", channels)
        _ALLOWED_CHANNELS_CACHE = channels
    return channels

def remove_allowed_channel(channel_id):
    """Removes a channel ID from the allowed list."""
    global _ALLOWED_CHANNELS_CACHE
    channels = get_allowed_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        set_server_setting("allowed_channels", channels)
        _ALLOWED_CHANNELS_CACHE = channels
    return channels