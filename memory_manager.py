import os
import json
from datetime import datetime
import re
import config
import shutil
import logging
import asyncio
from functools import partial

logger = logging.getLogger("MemoryManager")

def get_memory_filepath(channel_id, channel_name):
    safe_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
    return os.path.join(config.MEMORY_DIR, f"{safe_name}_{channel_id}.txt")

def wipe_all_memories():
    """Deletes all memory files from the Memory directory."""
    try:
        if not os.path.exists(config.MEMORY_DIR):
            return
        for filename in os.listdir(config.MEMORY_DIR):
            file_path = os.path.join(config.MEMORY_DIR, filename)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        logger.info("Wiped all memories.")
    except Exception as e:
        logger.error(f"Failed to wipe all memories: {e}")

def wipe_all_logs():
    """Deletes the Logs directory and recreates it."""
    try:
        if os.path.exists(config.LOGS_DIR):
            shutil.rmtree(config.LOGS_DIR)
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        logger.info("Wiped all logs.")
    except Exception as e:
        logger.error(f"Failed to wipe all logs: {e}")

def log_conversation(channel_name, user_name, user_id, content):
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

def _write_file_sync(filepath, content, mode='w', encoding='utf-8'):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, mode, encoding=encoding) as f:
        f.write(content)

async def write_context_buffer(messages, channel_id, channel_name, append_response=None):
    """
    Writes the current context window to a file for debugging/inspection.
    Now uses non-blocking I/O.
    """
    filepath = get_memory_filepath(channel_id, channel_name)
    loop = asyncio.get_running_loop()

    try:
        if append_response:
            clean_resp = append_response.replace('[', '(').replace(']', ')')
            content = f"[ASSISTANT_REPLY]\n{clean_resp}\n\n"
            await loop.run_in_executor(None, partial(_write_file_sync, filepath, content, 'a'))
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
                content = content.replace('[', '(').replace(']', ')')

            buffer.append(f"[{role}]\n{content}\n\n")
        
        full_content = "".join(buffer)
        await loop.run_in_executor(None, partial(_write_file_sync, filepath, full_content, 'w'))

    except Exception as e:
        logger.error(f"Failed to write memory file {filepath}: {e}")

def clear_channel_memory(channel_id, channel_name):
    filepath = get_memory_filepath(channel_id, channel_name)
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"=== MEMORY CLEARED ===\n")
    except Exception as e:
        logger.error(f"Failed to clear memory file: {e}")

# --- GOOD BOT LOGIC ---

def increment_good_bot(user_id, username):
    filepath = config.GOOD_BOT_FILE
    data = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f: data = json.load(f)
        except: pass
    
    user_id_str = str(user_id)
    if user_id_str in data:
        data[user_id_str]["count"] += 1
        data[user_id_str]["username"] = username 
    else:
        data[user_id_str] = {"username": username, "count": 1}
        
    try:
        with open(filepath, "w") as f: json.dump(data, f, indent=4)
        return data[user_id_str]["count"]
    except Exception as e:
        logger.error(f"Failed to save good bot data: {e}")
        return 0

def get_good_bot_leaderboard():
    filepath = config.GOOD_BOT_FILE
    if not os.path.exists(filepath): return []
    try:
        with open(filepath, "r") as f: data = json.load(f)
        leaderboard = []
        for uid, info in data.items(): leaderboard.append(info)
        leaderboard.sort(key=lambda x: x["count"], reverse=True)
        return leaderboard
    except: return []

# --- EMBED SUPPRESSION LOGIC ---

def get_suppressed_users():
    if os.path.exists(config.SUPPRESSED_USERS_FILE):
        try:
            with open(config.SUPPRESSED_USERS_FILE, "r") as f:
                return set(json.load(f))
        except: pass
    return set()

def toggle_suppressed_user(user_id):
    users = get_suppressed_users()
    uid_str = str(user_id)
    enabled = False
    
    if uid_str in users:
        users.remove(uid_str)
        enabled = False
    else:
        users.add(uid_str)
        enabled = True
        
    try:
        with open(config.SUPPRESSED_USERS_FILE, "w") as f:
            json.dump(list(users), f)
    except Exception as e:
        logger.error(f"Failed to save suppressed users: {e}")
        
    return enabled

def get_server_setting(key, default=True):
    if os.path.exists(config.SERVER_SETTINGS_FILE):
        try:
            with open(config.SERVER_SETTINGS_FILE, "r") as f:
                data = json.load(f)
                return data.get(key, default)
        except: pass
    return default

def set_server_setting(key, value):
    data = {}
    if os.path.exists(config.SERVER_SETTINGS_FILE):
        try:
            with open(config.SERVER_SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except: pass
    
    data[key] = value
    
    try:
        with open(config.SERVER_SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save server settings: {e}")
