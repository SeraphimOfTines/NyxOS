# ==========================================
#                NyxOS v1.0
#          Made lovingly by Calyptra
# ==========================================

import discord
from discord import app_commands
import aiohttp
import json
import logging
import re
import asyncio
import os
import sys
import base64
import mimetypes
from datetime import datetime, timedelta, timezone

# --- HELPER: Get Absolute Path ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_path(filename):
    return os.path.join(BASE_DIR, filename)

# ==========================================
# CONFIGURATION LOADER
# ==========================================

def load_secrets():
    """Loads secrets from config.txt into global scope."""
    try:
        with open(get_path("config.txt"), "r") as f:
            config_content = f.read()
        # Execute the config content to define the variables
        exec(config_content, globals())
    except FileNotFoundError:
        print(f"❌ CRITICAL ERROR: Could not find 'config.txt'. Please create it with the necessary variables.")
        # Exit or handle the error appropriately
        sys.exit(1)
    except Exception as e:
        print(f"❌ CRITICAL ERROR: An error occurred while loading 'config.txt': {e}")
        sys.exit(1)

# Load secrets from config.txt
load_secrets()

# File Constants
MEMORY_DIR = "Memory"
LOGS_DIR = "Logs"
ALLOWED_CHANNELS_FILE = "allowed_channels.json"
RESTART_META_FILE = "restart_metadata.json"
GOOD_BOT_FILE = "goodbot.json"

def load_config():
    try:
        # Ensure directories exist immediately
        os.makedirs(get_path(MEMORY_DIR), exist_ok=True)
        os.makedirs(get_path(LOGS_DIR), exist_ok=True)

        with open(get_path("token.txt"), "r") as f:
            token = f.read().strip()
            
        with open(get_path("system_prompt.txt"), "r") as f:
            system_prompt = f.read().strip()
            
        kagi_token = None
        try:
            with open(get_path("kagi_token.txt"), "r") as f:
                kagi_token = f.read().strip()
        except FileNotFoundError:
            print(f"ℹ️ Note: '{get_path('kagi_token.txt')}' not found. Web search will be disabled.")

        if not os.path.exists(get_path(ALLOWED_CHANNELS_FILE)):
            with open(get_path(ALLOWED_CHANNELS_FILE), "w") as f:
                json.dump([], f)
                
        with open(get_path(ALLOWED_CHANNELS_FILE), "r") as f:
            allowed_channels = json.load(f)
        
        try:
            with open(get_path("injected_prompt.txt"), "r") as f:
                injected_prompt = f.read().strip()
        except FileNotFoundError:
            print(f"ℹ️ Note: '{get_path('injected_prompt.txt')}' not found. Proceeding without extra injection.")
            injected_prompt = ""

        if injected_prompt:
            full_system_prompt = f"{system_prompt}\n\n{injected_prompt}"
        else:
            full_system_prompt = system_prompt
            
        return token, kagi_token, full_system_prompt, allowed_channels
    except FileNotFoundError as e:
        print(f"❌ CRITICAL ERROR: Could not find configuration file: {e.filename}")
        return None, None, None, []
    except json.JSONDecodeError:
        print(f"❌ CRITICAL ERROR: '{ALLOWED_CHANNELS_FILE}' is not valid JSON.")
        return None, None, None, []

def save_allowed_channels(channels_list):
    try:
        with open(get_path(ALLOWED_CHANNELS_FILE), "w") as f:
            json.dump(channels_list, f, indent=4)
        global ALLOWED_CHANNEL_IDS
        ALLOWED_CHANNEL_IDS = channels_list
    except Exception as e:
        print(f"⚠️ Failed to save allowed channels: {e}")

# Load config immediately
BOT_TOKEN, KAGI_API_TOKEN, SYSTEM_PROMPT_TEMPLATE, ALLOWED_CHANNEL_IDS = load_config()

# --- FAIL SAFE FOR MISSING TOKEN ---
if not BOT_TOKEN:
    print("❌ Cannot start: Token is missing. Please check token.txt.")
    sys.exit(1)

PLURALKIT_MESSAGE_API = "https://api.pluralkit.me/v2/messages/{}"
PLURALKIT_USER_API = "https://api.pluralkit.me/v2/users/{}"
PLURALKIT_SYSTEM_MEMBERS = "https://api.pluralkit.me/v2/systems/{}/members"
KAGI_SEARCH_URL = "https://kagi.com/api/v0/search"

# ==========================================
# BOT CODE
# ==========================================

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

class LMStudioBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.http_session = None
        self.pk_user_cache = {}   
        self.pk_proxy_tags = {}   
        self.my_system_members = set() 
        self.boot_time = discord.utils.utcnow()
        self.tree = app_commands.CommandTree(self)
        
        self.channel_cutoff_times = {}
        self.good_bot_cooldowns = {} # Stores User ID -> Timestamp
        self.processing_locks = set() # PREVENT DOUBLE PROCESSING
        self.active_views = {} # Stores {message_id: View} to allow updates
        self.last_bot_message_id = {} # Stores {channel_id: message_id} for last bot reply
        self.has_synced = False 
        
        # --- TRACK CLEARED CHANNELS ---
        self.boot_cleared_channels = set() 
        
        os.makedirs(get_path(MEMORY_DIR), exist_ok=True)
        os.makedirs(get_path(LOGS_DIR), exist_ok=True)

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        await self.fetch_my_system_data()

    # --- HELPER: Delayed Embed Suppress ---
    async def suppress_embeds_later(self, message, delay=5):
        """Waits a few seconds then suppresses embeds (cleans up clutter)."""
        await asyncio.sleep(delay)
        try:
            await message.edit(suppress=True)
        except Exception as e:
            pass
    
    # --- HELPER: Permission Check ---
    def is_authorized(self, user_id):
        return user_id in SERAPH_IDS or user_id in CHIARA_IDS

    # --- HELPER: Robust Mime Type Detector ---
    def get_safe_mime_type(self, attachment):
        filename = attachment.filename.lower()
        
        # 1. Priority: Check Extension (Fixes the Discord "png is webp" lie)
        if filename.endswith('.png'): return 'image/png'
        if filename.endswith(('.jpg', '.jpeg')): return 'image/jpeg'
        if filename.endswith('.webp'): return 'image/webp'
        
        # 2. Trust Discord if extension didn't catch it
        if attachment.content_type and attachment.content_type.startswith('image/'):
            return attachment.content_type

        # 3. System Registry Fallback
        guessed_type, _ = mimetypes.guess_type(attachment.filename)
        if guessed_type and guessed_type.startswith('image/'):
            return guessed_type

        # 4. Ultimate Fallback (Prevents "data:None")
        return 'image/png'

    # --- DATA FETCHING ---

    async def fetch_my_system_data(self):
        try:
            async with self.http_session.get(PLURALKIT_SYSTEM_MEMBERS.format(MY_SYSTEM_ID)) as resp:
                if resp.status == 200:
                    members = await resp.json()
                    for m in members:
                        if 'name' in m: self.my_system_members.add(m['name'])
                        if 'display_name' in m and m['display_name']: self.my_system_members.add(m['display_name'])
        except Exception as e:
            print(f"⚠️ Error fetching main system data: {e}")

    async def get_pk_user_data(self, user_id):
        if user_id in self.pk_user_cache:
            return self.pk_user_cache[user_id]

        url = PLURALKIT_USER_API.format(user_id)
        try:
            async with self.http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {'system_id': data.get('id'), 'tag': data.get('tag')}
                    self.pk_user_cache[user_id] = result
                    return result
                elif resp.status == 404:
                    self.pk_user_cache[user_id] = None
        except Exception as e:
            print(f"⚠️ PK User API Exception: {e}")
        return None

    async def get_system_proxy_tags(self, system_id):
        if system_id in self.pk_proxy_tags:
            return self.pk_proxy_tags[system_id]

        url = PLURALKIT_SYSTEM_MEMBERS.format(system_id)
        tags = []
        try:
            async with self.http_session.get(url) as resp:
                if resp.status == 200:
                    members = await resp.json()
                    for m in members:
                        ptags = m.get('proxy_tags', [])
                        for pt in ptags:
                            tags.append({'prefix': pt.get('prefix'), 'suffix': pt.get('suffix')})
                    self.pk_proxy_tags[system_id] = tags
        except Exception as e:
            print(f"⚠️ Error fetching proxy tags: {e}")
        return tags

    async def get_pk_message_data(self, message_id):
        url = PLURALKIT_MESSAGE_API.format(message_id)
        try:
            async with self.http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    member_name = data.get('member', {}).get('name')
                    member_display = data.get('member', {}).get('display_name')
                    final_name = member_display if member_display else member_name
                    
                    system_data = data.get('system', {})
                    system_id = system_data.get('id')
                    system_tag = system_data.get('tag')
                    sender_id = data.get('sender') 
                    
                    description = data.get('member', {}).get('description', "")
                    # --- SANITIZE BRACKETS FROM DESCRIPTION ---
                    if description:
                        description = description.replace('[', '(').replace(']', ')')
                    # ------------------------------------------
                    
                    return final_name, system_id, system_tag, sender_id, description
        except Exception as e:
            print(f"⚠️ PK Message API Exception: {e}")
        return None, None, None, None, None

    # --- TIME LOGIC ---

    def get_system_time(self):
        utc_now = datetime.now(timezone.utc)
        pst_offset = timedelta(hours=-8)
        pst_now = utc_now.astimezone(timezone(pst_offset))
        return pst_now.strftime("%A, %B %d, %Y"), pst_now.strftime("%I:%M %p")

    # --- WEB SEARCH LOGIC (KAGI) ---

    async def generate_search_queries(self, user_prompt, history_messages, force_search=False):
        if not KAGI_API_TOKEN: return None

        context_str = ""
        for msg in history_messages[-6:]:
            role = msg['role'].upper()
            content = msg['content']
            if isinstance(content, list):
                text_parts = [i['text'] for i in content if i['type'] == 'text']
                content = " ".join(text_parts)
            context_str += f"{role}: {content}\n"

        system_instruction = (
            "### INSTRUCTION ###\n"
            "You are a Research Query Generator. You do NOT answer the user. You output search engine queries.\n"
            "1. Analyze the User's Request.\n"
            "2. If the user explicitly asked for a search OR if the request requires factual data, generate 1 to 3 specific search queries.\n"
            "3. Queries should be Google-dork style (keywords only).\n"
            f"{'4. The user has EXPLICITLY requested a search (!web). You MUST generate queries.' if force_search else '4. If NO search is needed (casual chat, opinions), output exactly: NO_SEARCH'}\n"
        )

        user_content = f"### CONTEXT ###\n{context_str}\n\n### CURRENT REQUEST ###\n{user_prompt}\n\n### GENERATE QUERIES ###"

        decision_messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content}
        ]

        payload = {
            "messages": decision_messages,
            "temperature": 0.1, 
            "max_tokens": 150,
            "stream": False
        }

        try:
            async with self.http_session.post(LM_STUDIO_URL, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data['choices'][0]['message']['content'].strip()
                    if "NO_SEARCH" in content and not force_search: return []
                    queries = [q.strip() for q in content.split('\n') if q.strip()]
                    clean_queries = []
                    for q in queries:
                        q = re.sub(r'^\d+\.\s*|-\s*', '', q)
                        if q.lower() != user_prompt.lower(): clean_queries.append(q)
                    if force_search and not clean_queries: return [user_prompt]
                    return clean_queries[:3]
        except Exception as e:
            print(f"⚠️ Query Generation Failed: {e}")
            if force_search: return [user_prompt]
        return []

    async def search_kagi(self, query):
        if not KAGI_API_TOKEN: return "Error: Config missing."
        print(f"🔍 [KAGI] Searching for: '{query}'")
        headers = {"Authorization": f"Bot {KAGI_API_TOKEN}"}
        params = {"q": query, "limit": 6} 
        try:
            async with self.http_session.get(KAGI_SEARCH_URL, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", [])
                    if not results: return "No results found."
                    summary = ""
                    for i, item in enumerate(results, 1):
                        title = item.get("title", "No Title")
                        snippet = item.get("snippet", "No Snippet")
                        if len(snippet) > 350: snippet = snippet[:350] + "..."
                        url = item.get("url", "#")
                        summary += f"{i}. [{title}]({url})\n   {snippet}\n\n"
                    return summary
                else: return f"Error: Kagi API returned status {resp.status}"
        except Exception as e: return f"Error searching Kagi: {e}"

    # --- GOOD BOT LOGIC ---

    def increment_good_bot(self, user_id, username):
        filepath = get_path(os.path.join(MEMORY_DIR, GOOD_BOT_FILE))
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
            print(f"⚠️ Failed to save good bot data: {e}")
            return 0

    def get_good_bot_leaderboard(self):
        filepath = get_path(os.path.join(MEMORY_DIR, GOOD_BOT_FILE))
        if not os.path.exists(filepath): return []
        try:
            with open(filepath, "r") as f: data = json.load(f)
            leaderboard = []
            for uid, info in data.items(): leaderboard.append(info)
            leaderboard.sort(key=lambda x: x["count"], reverse=True)
            return leaderboard
        except: return []

    # --- CLEANING LOGIC ---

    def matches_proxy_tag(self, content, tags):
        for tag in tags:
            prefix, suffix = tag.get('prefix') or "", tag.get('suffix') or ""
            if not prefix and not suffix: continue
            c_clean = content.strip()
            p_clean = prefix.strip()
            s_clean = suffix.strip()
            match = True
            if p_clean and not c_clean.startswith(p_clean): match = False
            if s_clean and not c_clean.endswith(s_clean): match = False
            if match: return True
        return False

    def clean_name_logic(self, raw_name, system_tag=None):
        name = raw_name
        if system_tag:
            if system_tag in name: name = name.replace(system_tag, "")
            else:
                stripped_tag = system_tag.strip()
                if stripped_tag in name: name = name.replace(stripped_tag, "")
        return re.sub(r'\s*([\[\(\{<\|⛩].*?[\]\}\)>\|⛩])\s*', '', name).strip()

    def get_identity_suffix(self, user_id, system_id, member_name=None):
        try: uid_int = int(user_id) if user_id else None
        except: uid_int = None
        
        is_seraph = False
        if uid_int in SERAPH_IDS: is_seraph = True
        elif system_id == MY_SYSTEM_ID: is_seraph = True
        elif member_name and member_name in self.my_system_members: is_seraph = True
        
        if is_seraph: return " (Seraph)"
        if uid_int in CHIARA_IDS: return " (Chiara) (Not Seraphim)"
        return " (Not Seraphim)"

    async def is_proxy_trigger_message(self, message):
        if message.webhook_id: return False
        if message.author.id in SERAPH_IDS:
            tags = await self.get_system_proxy_tags(MY_SYSTEM_ID)
            if self.matches_proxy_tag(message.content, tags): return True
        
        user_sys_data = await self.get_pk_user_data(message.author.id)
        if not user_sys_data: return False
        sys_id = user_sys_data['system_id']
        if not sys_id: return False
        tags = await self.get_system_proxy_tags(sys_id)
        return self.matches_proxy_tag(message.content, tags)

    # --- FILE MANAGEMENT ---

    def get_memory_filepath(self, channel_id, channel_name):
        safe_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        return get_path(os.path.join(MEMORY_DIR, f"{safe_name}_{channel_id}.txt"))
    
    def log_conversation(self, channel_name, user_name, user_id, content):
        """Logs chat messages to a daily rolling log file."""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_log_dir = get_path(os.path.join(LOGS_DIR, today))
        os.makedirs(daily_log_dir, exist_ok=True)
        
        safe_channel = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        log_file = os.path.join(daily_log_dir, f"{safe_channel}.log")
        
        if not os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== LOG STARTED: {today} ===\nSYSTEM PROMPT:\n{SYSTEM_PROMPT_TEMPLATE}\n====================================\n\n")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {user_name} [{user_id}]: {content}\n")
        except Exception as e:
            print(f"⚠️ Failed to write to log: {e}")

    async def write_context_buffer(self, messages, channel_id, channel_name, append_response=None):
        filepath = self.get_memory_filepath(channel_id, channel_name)
        try:
            if append_response:
                with open(filepath, "a", encoding="utf-8") as f:
                    # --- SANITIZATION FOR LOGS ---
                    clean_resp = append_response.replace('[', '(').replace(']', ')')
                    f.write(f"[ASSISTANT_REPLY]\n{clean_resp}\n\n")
                return
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"=== MEMORY BUFFER FOR #{channel_name} ({channel_id}) ===\n")
                f.write(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=====================================================\n\n")
                for msg in messages:
                    role = msg['role'].upper()
                    content = msg['content']
                    # ---- CLEANUP FOR LOG FILE: Convert list/images to readable string ----
                    if isinstance(content, list):
                        text_parts = []
                        has_image = False
                        for item in content:
                            if item['type'] == 'text': text_parts.append(item['text'])
                            elif item['type'] == 'image_url': has_image = True
                        content = " ".join(text_parts)
                        if has_image: content += " (IMAGE DATA SENT TO AI)"
                    # ----------------------------------------------------------------------

                    # --- SANITIZATION (Catch-All) ---
                    if isinstance(content, str):
                        # Remove search tags FIRST, then sanitize brackets
                        if "<search_results>" in content:
                            content = re.sub(r'<search_results>.*?</search_results>', '(WEB SEARCH RESULTS OMITTED FROM LOG)', content, flags=re.DOTALL)
                        
                        # Nuclear option: Replace all remaining brackets to prevent structure corruption in LOGS
                        content = content.replace('[', '(').replace(']', ')')
                    # -------------------------------

                    f.write(f"[{role}]\n{content}\n\n")
        except Exception as e:
            print(f"⚠️ Failed to write memory file {filepath}: {e}")

    def clear_channel_memory(self, channel_id, channel_name):
        filepath = self.get_memory_filepath(channel_id, channel_name)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"=== MEMORY CLEARED ===\n")
            self.channel_cutoff_times[channel_id] = discord.utils.utcnow()
        except Exception as e:
            print(f"⚠️ Failed to clear memory file: {e}")

    # --- CORE AI (FAIL-SAFE) ---

    async def query_lm_studio(self, user_prompt, username, identity_suffix, history_messages, channel_obj, image_data_uri=None, member_description=None, search_context=None, reply_context_str=""):
        date_str, time_str = self.get_system_time()
        time_header = f"Current Date: {date_str}\nCurrent Time: {time_str}\n\n"

        # --- FIX: REPLACE PLACEHOLDERS ---
        base_prompt = SYSTEM_PROMPT_TEMPLATE \
            .replace("{{USER_NAME}}", "the people in this chatroom") \
            .replace("{{Seraphim}}", "Seraphim") \
            .replace("{{CONTEXT}}", "") \
            .replace("{{CURRENT_WEEKDAY}}", datetime.now().strftime("%A")) \
            .replace("{{CURRENT_DATETIME}}", f"{date_str}, {time_str}")
        # ---------------------------------
            
        if member_description:
            # --- BRACKET SANITIZATION IN PROMPT ---
            clean_desc = member_description.replace('[', '(').replace(']', ')')
            # CHANGED: Replaced outer [] with () to prevent parsing errors
            base_prompt += f"\n\n(Context: The user '{username}' has the following description: {clean_desc})"
            # --------------------------------------

        if search_context:
            base_prompt += f"\n\n<search_results>\nThe user requested a web search. Here are the results:\n{search_context}\n</search_results>\n\nINSTRUCTION: Use the above search results to answer the user's request accurately. Cite the sources using the format: [Source Title](URL)."

        formatted_system_prompt = time_header + base_prompt
        display_name_for_ai = f"{username}{identity_suffix}"

        # --- CHANGED: REVERTED TO STANDARD SYSTEM ROLE ---
        raw_messages = [{"role": "system", "content": formatted_system_prompt}]
        
        # --- HISTORY SANITIZATION ---
        cleaned_history = []
        skip_next = False
        
        for i, msg in enumerate(history_messages):
            # FILTER 1: Skip if message contains the bot's own startup message
            content_str = str(msg.get('content', ''))
            if "I'm back online! Hi!" in content_str:
                continue

            # FILTER 2: Fix User -> User Pattern (caused by Ghosts + Webhooks)
            if i < len(history_messages) - 1:
                curr_role = msg.get('role')
                next_role = history_messages[i+1].get('role')
                if curr_role == 'user' and next_role == 'user':
                    continue
            
            cleaned_history.append(msg)
        
        # FILTER 3: Fix Start of Conversation (Assistant cannot be first)
        while len(cleaned_history) > 0 and cleaned_history[0].get('role') == 'assistant':
            cleaned_history.pop(0)
            
        raw_messages.extend(cleaned_history)
        # ----------------------------------------------------------------

        # Add Reply Context to Current Message
        user_text_content = f"{display_name_for_ai}{reply_context_str} says: {user_prompt}"
        
        if image_data_uri:
            current_message_content = [
                {"type": "text", "text": user_text_content},
                {"type": "image_url", "image_url": {"url": image_data_uri}}
            ]
        else:
            current_message_content = user_text_content

        raw_messages.append({"role": "user", "content": current_message_content})

        # === COALESCE LOGIC ===
        merged_messages = []
        for msg in raw_messages:
            if not merged_messages:
                merged_messages.append(msg)
                continue
            
            last_msg = merged_messages[-1]
            
            if last_msg['role'] == msg['role']:
                # Convert both to lists to merge properly
                if isinstance(last_msg['content'], str):
                    last_msg['content'] = [{"type": "text", "text": last_msg['content']}]
                
                current_list = msg['content']
                if isinstance(current_list, str):
                    current_list = [{"type": "text", "text": current_list}]
                
                last_msg['content'].extend(current_list)
            else:
                merged_messages.append(msg)

        # Logic check: Remove immediate assistant response if it follows system prompt incorrectly
        if len(merged_messages) > 1 and merged_messages[1]['role'] == 'assistant':
            merged_messages.pop(1)

        await self.write_context_buffer(merged_messages, channel_obj.id, channel_obj.name)
        
        # === FAIL-SAFE REQUEST ===
        try:
            return await self._send_payload(merged_messages)
        except Exception as e:
            # Fallback if Image failed (Error 400, etc.)
            if "400" in str(e) or "base64" in str(e).lower():
                print(f"⚠️ Vision Payload Failed ({e}). Retrying text-only...")
                text_only_messages = self._strip_images(merged_messages)
                return await self._send_payload(text_only_messages)
            raise e

    async def _send_payload(self, messages):
        headers = {"Content-Type": "application/json"}
        
        # --- UNIVERSAL BRACKET SANITIZER ---
        # Iterate through the final payload and replace [] with () in all text content.
        # This is the final line of defense.
        cleaned_messages = []
        for msg in messages:
            new_msg = msg.copy()
            content = new_msg.get('content')
            
            if isinstance(content, str):
                new_msg['content'] = content.replace('[', '(').replace(']', ')')
            elif isinstance(content, list):
                new_list = []
                for item in content:
                    new_item = item.copy()
                    if new_item.get('type') == 'text':
                        new_item['text'] = new_item['text'].replace('[', '(').replace(']', ')')
                    new_list.append(new_item)
                new_msg['content'] = new_list
                
            cleaned_messages.append(new_msg)
        # -----------------------------------
        
        payload = {
            "messages": cleaned_messages,
            "temperature": 0.6,
            "max_tokens": -1,
            "stream": False
        }
        
        # --- DEBUG: DUMP PAYLOAD ---
        print(f"\n--- DEBUG PAYLOAD ({datetime.now().strftime('%H:%M:%S')}) ---")
        role_sequence = " -> ".join([m.get('role', 'unknown') for m in cleaned_messages])
        print(f"Roles: {role_sequence}")
        # print(json.dumps(payload, indent=2, ensure_ascii=False)) # Uncomment to see full body
        print("---------------------------------------------------\n")
        # ---------------------------

        async with self.http_session.post(LM_STUDIO_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data['choices'][0]['message']['content']
            else:
                error_text = await resp.text()
                print(f"\n❌ LM Studio Error ({resp.status}): {error_text}\n")
                raise Exception(f"LM Studio Error {resp.status}: {error_text}")

    def _strip_images(self, messages):
        clean_messages = []
        for msg in messages:
            content = msg['content']
            if isinstance(content, list):
                text_parts = [item['text'] for item in content if item['type'] == 'text']
                new_content = " ".join(text_parts)
                if any(item['type'] == 'image_url' for item in content):
                    new_content += " (Image Download Failed)"
                clean_messages.append({"role": msg['role'], "content": new_content})
            else:
                clean_messages.append(msg)
        return clean_messages

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

client = LMStudioBot()

# ==========================================
# SLASH COMMANDS
# ==========================================

@client.tree.command(name="addchannel", description="Add the current channel to the bot's whitelist.")
async def add_channel_command(interaction: discord.Interaction):
    if not client.is_authorized(interaction.user.id) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("🤨 You're not a Seraph. Shoo!", ephemeral=True)
        return
    if interaction.channel_id in ALLOWED_CHANNEL_IDS:
        await interaction.response.send_message("✅ Channel already whitelisted.", ephemeral=True)
    else:
        ALLOWED_CHANNEL_IDS.append(interaction.channel_id)
        save_allowed_channels(ALLOWED_CHANNEL_IDS)
        await interaction.response.send_message(f"😄 I'll talk in this channel!", ephemeral=True)

@client.tree.command(name="removechannel", description="Remove the current channel from the bot's whitelist.")
async def remove_channel_command(interaction: discord.Interaction):
    if not client.is_authorized(interaction.user.id) and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("🤨 You're not a Seraph. Shoo!", ephemeral=True)
        return
    if interaction.channel_id in ALLOWED_CHANNEL_IDS:
        ALLOWED_CHANNEL_IDS.remove(interaction.channel_id)
        save_allowed_channels(ALLOWED_CHANNEL_IDS)
        await interaction.response.send_message(f"🤐 I'll ignore this channel!", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Channel not in whitelist.", ephemeral=True)

@client.tree.command(name="reload", description="Full restart of the bot process.")
async def reload_command(interaction: discord.Interaction):
    if not client.is_authorized(interaction.user.id):
        await interaction.response.send_message("🤨 You're not a Seraph. Shoo!", ephemeral=True)
        return

    await interaction.response.send_message("🔴 Rebooting . . .", ephemeral=False)
    
    meta = {"channel_id": interaction.channel_id}
    try:
        with open(get_path(RESTART_META_FILE), "w") as f:
            json.dump(meta, f)
            f.flush()
            os.fsync(f.fileno())
            print(f"📝 Wrote restart metadata: {meta}")
    except Exception as e:
        print(f"⚠️ Failed to write restart metadata: {e}")

    # Close session cleanly before restart
    await client.close()
    python = sys.executable
    os.execl(python, python, *sys.argv)

@client.tree.command(name="clearmemory", description="Clear the bot's memory for this channel.")
async def clearmemory_command(interaction: discord.Interaction):
    if not client.is_authorized(interaction.user.id):
        await interaction.response.send_message("🤨 You're not a Seraph. Shoo!", ephemeral=True)
        return
    
    client.clear_channel_memory(interaction.channel_id, interaction.channel.name)
    await interaction.response.send_message("🧹 I cleared my memory!", ephemeral=True)

@client.tree.command(name="reportbug", description="Submit a bug report.")
async def reportbug_command(interaction: discord.Interaction):
    # This just opens the modal directly for command users
    # Jump URL is None since it's not from a button on a message
    await interaction.response.send_modal(BugReportModal(None))

@client.tree.command(name="goodbot", description="Show the Good Bot Leaderboard.")
async def good_bot_leaderboard(interaction: discord.Interaction):
    leaderboard = client.get_good_bot_leaderboard()
    if not leaderboard:
        await interaction.response.send_message("No one has called me a good bot yet! 🥺", ephemeral=False)
        return

    total_good_bots = sum(user['count'] for user in leaderboard)
    
    chart_text = "💙 I'm such a good bot! 💙\n\n"
    for i, user_data in enumerate(leaderboard[:10], 1):
        chart_text += f"**{i}.** {user_data['username']} — **{user_data['count']}**\n"
    
    chart_text += f"\n**Total:** {total_good_bots} Good Bots 💙"
    
    await interaction.response.send_message(chart_text, ephemeral=False)

# ==========================================
# BUG REPORT MODAL
# ==========================================

class BugReportModal(discord.ui.Modal, title="Report a Bug"):
    report_title = discord.ui.TextInput(label="Bug Title", style=discord.TextStyle.short, required=True, max_length=100, placeholder="Short summary of the bug")
    report_body = discord.ui.TextInput(label="Bug Description", style=discord.TextStyle.paragraph, required=True, placeholder="Detailed description of what happened...", min_length=10)

    def __init__(self, message_url, original_message_id=None, channel_id=None):
        super().__init__()
        self.message_url = message_url
        self.original_message_id = original_message_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.client.get_channel(BUG_REPORT_CHANNEL_ID)
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(BUG_REPORT_CHANNEL_ID)
            except:
                await interaction.response.send_message("❌ Could not find bug report channel. Please contact admin.", ephemeral=True)
                return

        try:
            msg = await channel.send(f"🐛 **Bug Report:** {self.report_title.value}")
            thread = await msg.create_thread(name=f"Bug: {self.report_title.value}")
            
            embed = discord.Embed(description=self.report_body.value, color=discord.Color.red())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            
            link_val = f"[Jump to Message]({self.message_url})" if self.message_url else "N/A (Slash Command)"
            embed.add_field(name="Source Message", value=link_val)
            
            await thread.send(embed=embed)
            await interaction.response.send_message("✅ Thanks for the help! You're the best! 😉", ephemeral=True)
            
            # Update button on original message if IDs were passed
            if self.original_message_id and self.channel_id:
                try:
                    origin_channel = interaction.client.get_channel(self.channel_id) or await interaction.client.fetch_channel(self.channel_id)
                    origin_msg = await origin_channel.fetch_message(self.original_message_id)
                    
                    if self.original_message_id in interaction.client.active_views:
                        view = interaction.client.active_views[self.original_message_id]
                        updated = False
                        for child in view.children:
                            if getattr(child, "custom_id", "") == "bug_report_btn":
                                child.label = "Thanks!"
                                child.disabled = True
                                updated = True
                        if updated:
                            await origin_msg.edit(view=view)
                except Exception as e:
                    print(f"⚠️ Failed to update bug report button: {e}")

        except Exception as e:
             await interaction.response.send_message(f"❌ Error sending report: {e}", ephemeral=True)

# ==========================================
# VIEW
# ==========================================

class ResponseView(discord.ui.View):
    def __init__(self, original_prompt, user_id, username, identity_suffix, history_messages, channel_obj, image_data_uri, member_description, search_context, reply_context_str):
        super().__init__(timeout=None)
        self.original_prompt = original_prompt
        self.user_id = user_id
        self.username = username
        self.identity_suffix = identity_suffix
        self.history_messages = history_messages
        self.channel_obj = channel_obj
        self.image_data_uri = image_data_uri
        self.member_description = member_description
        self.search_context = search_context
        self.reply_context_str = reply_context_str

    @discord.ui.button(label="🔃 Retry", style=discord.ButtonStyle.primary, custom_id="retry_btn", row=0)
    async def retry_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.label = "Regenerating . . ."
        button.disabled = True
        await interaction.response.edit_message(view=self, content="# <a:Thinking:1322962569300017214> Thinking . . .")

        new_response_text = await client.query_lm_studio(
            self.original_prompt, self.username, self.identity_suffix, 
            self.history_messages, self.channel_obj, self.image_data_uri, self.member_description, self.search_context, self.reply_context_str
        )
        new_response_text = new_response_text.replace("(Seraph)", "").replace("(Chiara)", "").replace("(Not Seraphim)", "")
        
        # Remove internal (re: User) tags from output
        new_response_text = re.sub(r'\s*\(re:.*?\)', '', new_response_text).strip()
        
        button.label = "Regenerated!"
        button.disabled = True 
        
        await interaction.edit_original_response(content=new_response_text, view=self)
        
        if client.loop:
             client.loop.create_task(client.suppress_embeds_later(interaction.message, delay=5))

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger, custom_id="delete_btn", row=0)
    async def delete_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # UI Update first
        await interaction.response.edit_message(content="# <a:SeraphCometFire:1326369374755491881> Message deleted <a:SeraphCometFire:1326369374755491881>", view=None)
        await asyncio.sleep(3)
        try: await interaction.message.delete()
        except: pass

    @discord.ui.button(label="Good Bot! 💙", style=discord.ButtonStyle.success, custom_id="good_bot_btn", row=0)
    async def good_bot_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Cooldown Check
        now = datetime.now().timestamp()
        last_time = client.good_bot_cooldowns.get(interaction.user.id, 0)
        
        if now - last_time < 5:
            await interaction.response.send_message("🤚🏻 Fucking CHILL! 😒", ephemeral=True)
            return
            
        # Valid Click
        client.good_bot_cooldowns[interaction.user.id] = now
        count = client.increment_good_bot(interaction.user.id, interaction.user.display_name)
        
        # Update Button
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        button.label = f"Good Bot: {count}" 
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🐛 Bug Report", style=discord.ButtonStyle.secondary, custom_id="bug_report_btn", row=0)
    async def bug_report_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Pass IDs to allow updating the button after submission
        await interaction.response.send_modal(
            BugReportModal(
                interaction.message.jump_url, 
                original_message_id=interaction.message.id, 
                channel_id=interaction.channel.id
            )
        )

    @discord.ui.button(label="🧠 Flush Memory", style=discord.ButtonStyle.danger, custom_id="clear_mem_btn", row=0)
    async def clear_memory_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        client.clear_channel_memory(self.channel_obj.id, self.channel_obj.name)
        button.label = "🤯 Memory Cleared"
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        await interaction.response.edit_message(view=self)

@client.event
async def on_ready():
    print('# ==========================================')
    print('#                NyxOS v1.0')
    print('#          Made lovingly by Calyptra')
    print('# ==========================================')
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print(f'Targeting LM Studio at: {LM_STUDIO_URL}')
    print(f'Memory Directory: {get_path(MEMORY_DIR)}/')
    
    with open(get_path("buffer.txt"), "w", encoding="utf-8") as f: f.write("")
    print('NyxOS: I\'m ready to go! 💙')
    
    client.has_synced = True

    # Check for restart metadata
    restart_data = None
    if os.path.exists(get_path(RESTART_META_FILE)):
        try:
            with open(get_path(RESTART_META_FILE), "r") as f:
                restart_data = json.load(f)
            os.remove(get_path(RESTART_META_FILE))
        except: pass

    # Determine target channel for boot message
    target_channel_id = None
    if restart_data and restart_data.get("channel_id"):
        target_channel_id = restart_data.get("channel_id")
    elif STARTUP_CHANNEL_ID:
        target_channel_id = STARTUP_CHANNEL_ID

    # Send Bootup Message
    if target_channel_id:
        try:
            channel = await client.fetch_channel(target_channel_id)
            if channel:
                await channel.send("🟢 I'm back online! Hi!")
                print(f"✅ Startup message sent to channel {target_channel_id}")
        except Exception as e:
            print(f"⚠️ Failed to send startup message: {e}")

@client.event
async def on_message(message):
    if message.author == client.user: return

    # --- PROCESSSING LOCK (DOUBLE MESSAGE FIX) ---
    if message.id in client.processing_locks:
        return
    
    # Only add lock if we proceed to processing
    
    try:
        if message.content == "!updateslashcommands" and client.is_authorized(message.author.id):
            await message.channel.send("🔄 Updating slash commands...")
            try:
                for guild in client.guilds:
                    client.tree.clear_commands(guild=guild)
                await client.tree.sync()
                
                for guild in client.guilds:
                    client.tree.copy_global_to(guild=guild)
                    await client.tree.sync(guild=guild)
                    
                await message.channel.send("✅ Commands synced and duplicates removed.")
            except Exception as e: await message.channel.send(f"❌ Error: {e}")
            return

        if message.content == "!forcesync" and client.is_authorized(message.author.id):
            await message.channel.send("🔄 Syncing...")
            try:
                client.tree.copy_global_to(guild=message.guild)
                await client.tree.sync(guild=message.guild)
                await message.channel.send("✅ Synced.")
            except Exception as e: await message.channel.send(f"❌ Error: {e}")
            return

        if message.content == "!fixduplicates" and client.is_authorized(message.author.id):
            await message.channel.send("🧹 Clearing...")
            try:
                client.tree.clear_commands(guild=message.guild)
                await client.tree.sync(guild=message.guild)
                await message.channel.send("✅ Cleared.")
            except Exception as e: await message.channel.send(f"❌ Error: {e}")
            return

        if message.webhook_id is None:
            is_trigger = await client.is_proxy_trigger_message(message)
            if is_trigger:
                return

        should_respond = False
        if client.user in message.mentions: should_respond = True
        if not should_respond:
            if message.role_mentions:
                for role in message.role_mentions:
                    if role.id in BOT_ROLE_IDS: should_respond = True; break
            if not should_respond:
                for rid in BOT_ROLE_IDS:
                    if f"<@&{rid}>" in message.content: should_respond = True; break
        if not should_respond and message.reference and message.reference.message_id:
            try:
                ref_msg = message.reference.resolved or await message.channel.fetch_message(message.reference.message_id)
                if ref_msg.author == client.user: should_respond = True
            except: pass 
            
        # Text Cooldown & Logic
        is_good_bot = "good bot" in message.content.lower()
        is_ping = client.user in message.mentions
        is_reply_to_me = False
        
        target_message_id = None
        
        if message.reference:
             try:
                 ref = message.reference.resolved or await message.channel.fetch_message(message.reference.message_id)
                 if ref.author.id == client.user.id:
                     is_reply_to_me = True
                     target_message_id = ref.id
             except: pass
        
        if is_good_bot and (is_ping or is_reply_to_me):
            if not target_message_id:
                target_message_id = client.last_bot_message_id.get(message.channel.id)

            now = datetime.now().timestamp()
            last_time = client.good_bot_cooldowns.get(message.author.id, 0)
            
            # FIXED: Removed the duplicate "draft" logic block that was causing double executions
            # and left only the complete, refactored block below.

            if now - last_time > 5:
                 # Call increment and capture count
                 count = client.increment_good_bot(message.author.id, message.author.display_name)
                 client.good_bot_cooldowns[message.author.id] = now
                 try:
                     await message.add_reaction("💙")
                 except: pass
                 
                 if target_message_id and target_message_id in client.active_views:
                     view = client.active_views[target_message_id]
                     button_updated = False
                     for child in view.children:
                         if getattr(child, "custom_id", "") == "good_bot_btn":
                             if not child.disabled:
                                 child.disabled = True
                                 child.style = discord.ButtonStyle.secondary
                                 child.label = f"Good Bot: {count}"
                                 button_updated = True
                      
                     if button_updated:
                         try:
                             if message.reference and message.reference.message_id == target_message_id and message.reference.resolved:
                                 ref_msg = message.reference.resolved
                             else:
                                 ref_msg = await message.channel.fetch_message(target_message_id)
                             await ref_msg.edit(view=view)
                         except: pass

            return

        if should_respond:
            if message.channel.id not in ALLOWED_CHANNEL_IDS: return

            # --- NEW: BOOT MEMORY WIPE ---
            if message.channel.id not in client.boot_cleared_channels:
                print(f"🧹 First message in #{message.channel.name} since boot. Wiping memory.")
                client.clear_channel_memory(message.channel.id, message.channel.name)
                client.boot_cleared_channels.add(message.channel.id)
            # -----------------------------

            client.processing_locks.add(message.id)

            # --- PLURALKIT GUARDRAIL (GHOST DETECTION) ---
            # If this is a user message (not a webhook), we MUST wait to see if it gets
            # deleted by PluralKit/Tupperbox before we process it.
            if message.webhook_id is None:
                await asyncio.sleep(2.0) # Wait 2s for deletion/proxying
                try:
                    # Check 1: Does message still exist?
                    await message.channel.fetch_message(message.id)
                    
                    # Check 2: Did a webhook message appear ANYWHERE in the last 15 messages?
                    # Increased limit to 15 to catch rapid webhook posts in busy channels
                    async for recent in message.channel.history(limit=15):
                        if recent.webhook_id is not None:
                             # If a webhook exists closely in time (within 3 seconds), abort.
                             # This handles both "before" and "after" scenarios due to clock drift.
                             diff = (recent.created_at - message.created_at).total_seconds()
                             if abs(diff) < 3.0:
                                 # print(f"👻 Ghost message detected (ID: {message.id}). Aborting.")
                                 return
                            
                except (discord.NotFound, discord.HTTPException):
                    # Message was deleted (likely proxied), so we abort processing.
                    return 
            # ---------------------------

            # --- DEBUG: PRINT PROCESSING INFO ---
            print(f"Processing Message from {message.author.name} (ID: {message.id}, Webhook: {message.webhook_id})")
            # ------------------------------------

            async with message.channel.typing():
                image_data_uri = None
                if message.attachments:
                    for att in message.attachments:
                        safe_mime = client.get_safe_mime_type(att)
                        is_image = (safe_mime.startswith('image/'))
                        
                        if is_image and att.size < 8 * 1024 * 1024:
                            try:
                                img_bytes = await att.read()
                                b64_str = base64.b64encode(img_bytes).decode('utf-8')
                                image_data_uri = f"data:{safe_mime};base64,{b64_str}"
                                break
                            except Exception as e: print(f"⚠️ Error processing image: {e}")

                clean_prompt = re.sub(r'<@!?{}>'.format(client.user.id), '', message.content)
                for rid in BOT_ROLE_IDS: clean_prompt = re.sub(r'<@&{}>'.format(rid), '', clean_prompt)
                clean_prompt = clean_prompt.replace(f"@{client.user.display_name}", "").replace(f"@{client.user.name}", "")
                # --- INPUT SANITIZATION: Prevent user bracket injection ---
                clean_prompt = clean_prompt.strip().replace("? ?", "?").replace("! ?", "!?").replace('[', '(').replace(']', ')')
                # --------------------------------------------------------

                force_search = False
                search_context = None
                if "!web" in clean_prompt:
                    clean_prompt = clean_prompt.replace("!web", "").strip()
                    force_search = True

                real_name = message.author.display_name
                system_tag = None
                sender_id = None
                system_id = None
                member_description = None
                
                if message.webhook_id:
                    pk_name, pk_sys_id, pk_tag, pk_sender, pk_desc = await client.get_pk_message_data(message.id)
                    if pk_name:
                        real_name = pk_name
                        system_tag = pk_tag
                        sender_id = pk_sender
                        system_id = pk_sys_id
                        member_description = pk_desc
                else:
                    sender_id = message.author.id
                    user_sys_data = await client.get_pk_user_data(sender_id)
                    if user_sys_data: 
                        system_tag = user_sys_data['tag']
                        system_id = user_sys_data['system_id']

                clean_name = client.clean_name_logic(real_name, system_tag)
                identity_suffix = client.get_identity_suffix(sender_id, system_id, clean_name)

                client.log_conversation(message.channel.name, real_name, sender_id or "UNKNOWN_ID", clean_prompt)

                history_messages = []
                async for prev_msg in message.channel.history(limit=CONTEXT_WINDOW + 5, before=message):
                    cutoff = client.channel_cutoff_times.get(message.channel.id)
                    if cutoff and prev_msg.created_at < cutoff: break
                    if prev_msg.webhook_id is None:
                        if await client.is_proxy_trigger_message(prev_msg): continue 

                    p_content = prev_msg.clean_content.strip()
                    has_image_history = any(att.content_type and att.content_type.startswith('image/') for att in prev_msg.attachments)
                    if not p_content and not has_image_history: continue
                    
                    p_content = p_content.replace(f"@{client.user.display_name}", "").replace(f"@{client.user.name}", "")
                    # --- HISTORY SANITIZATION: Prevent user bracket injection ---
                    p_content = re.sub(r'<@!?{}>'.format(client.user.id), '', p_content).strip().replace('[', '(').replace(']', ')')
                    # ------------------------------------------------------------

                    current_msg_content = []
                    if p_content:
                        current_msg_content.append({"type": "text", "text": p_content})

                    img_count = sum(1 for m in history_messages if isinstance(m['content'], list) and any(i.get('type') == 'image_url' for i in m['content']))
                    
                    if prev_msg.attachments and img_count < 2:
                        for att in prev_msg.attachments:
                            safe_mime = client.get_safe_mime_type(att)
                            is_image = (safe_mime.startswith('image/'))
                            
                            if is_image and att.size < 8 * 1024 * 1024: 
                                try:
                                    img_bytes = await att.read()
                                    b64_str = base64.b64encode(img_bytes).decode('utf-8')
                                    if b64_str:
                                            current_msg_content.append({
                                                "type": "image_url", 
                                                "image_url": {"url": f"data:{safe_mime};base64,{b64_str}"}
                                            })
                                except: pass

                    if not current_msg_content: continue

                    if prev_msg.author == client.user:
                        reply_context = ""
                        if prev_msg.reference:
                            if prev_msg.reference.resolved and isinstance(prev_msg.reference.resolved, discord.Message):
                                ref_auth = prev_msg.reference.resolved.author
                                reply_context = f" (re: {ref_auth.display_name})"
                        
                        clean_reply = re.sub(r'^(@\S+|^\<@\S+\>)\s*', '', p_content).strip()
                        clean_reply = re.sub(r'\s*\(re:.*?\)$', '', clean_reply).strip()
                        
                        history_messages.append({"role": "assistant", "content": f"{clean_reply}{reply_context}"})
                    else:
                        p_author_name = prev_msg.author.display_name
                        p_sender_id = prev_msg.author.id if not prev_msg.webhook_id else None
                        p_clean_name = client.clean_name_logic(p_author_name, None)
                        p_suffix = client.get_identity_suffix(p_sender_id, None, p_clean_name)
                        
                        context_tags = []
                        if prev_msg.reference:
                            if prev_msg.reference.resolved and isinstance(prev_msg.reference.resolved, discord.Message):
                                ref_name = prev_msg.reference.resolved.author.display_name
                                context_tags.append(f"(re: {ref_name})")

                        if client.user in prev_msg.mentions:
                            context_tags.append("(to You)")
                        context_str = " ".join(context_tags)
                        
                        prefix = f"{p_clean_name}{p_suffix} {context_str} says: "
                        
                        found_text = False
                        for item in current_msg_content:
                            if item['type'] == 'text':
                                item['text'] = prefix + item['text']
                                found_text = True
                                break
                        if not found_text:
                            current_msg_content.insert(0, {"type": "text", "text": prefix + "(Image)"})
                        
                        history_messages.append({"role": "user", "content": current_msg_content})
                
                if len(history_messages) > CONTEXT_WINDOW:
                    history_messages = history_messages[:CONTEXT_WINDOW]
                history_messages.reverse()

                search_queries = []
                if force_search:
                    search_queries = await client.generate_search_queries(clean_prompt, history_messages, force_search=True)

                if search_queries:
                    search_results_text = ""
                    for q in search_queries:
                        results = await client.search_kagi(q)
                        search_results_text += f"Query: {q}\n{results}\n\n"
                    search_context = search_results_text

                if not clean_prompt and image_data_uri: clean_prompt = "What is this image?"
                elif not clean_prompt and not search_queries:
                    await message.channel.send("🤔 You just gonna stare at me orrrr...? 💀")
                    return

                current_reply_context = ""
                if message.reference:
                    if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
                        current_reply_context = f" (Replying to {message.reference.resolved.author.display_name})"
                    elif message.reference.message_id:
                        try:
                            ref_msg = await message.channel.fetch_message(message.reference.message_id)
                            current_reply_context = f" (Replying to {ref_msg.author.display_name})"
                        except: pass

                if client.user in message.mentions:
                    # --- TARGET TAG FIX: Use Parentheses ---
                    current_reply_context += " (Target: NyxOS)"
                    # ---------------------------------------

                response_text = await client.query_lm_studio(
                    clean_prompt, clean_name, identity_suffix, history_messages, 
                    message.channel, image_data_uri, member_description, search_context, current_reply_context
                )
                
                client.log_conversation(message.channel.name, "NyxOS", client.user.id, response_text)
                
                response_text = response_text.replace("(Seraph)", "").replace("(Chiara)", "").replace("(Not Seraphim)", "")
                
                # Remove internal (re: User) tags from output
                response_text = re.sub(r'\s*\(re:.*?\)', '', response_text).strip()

                view = ResponseView(clean_prompt, message.author.id, clean_name, identity_suffix, history_messages, message.channel, image_data_uri, member_description, search_context, current_reply_context)

                try:
                    prev_msg_id = client.last_bot_message_id.get(message.channel.id)
                    if prev_msg_id and prev_msg_id in client.active_views:
                        prev_view = client.active_views[prev_msg_id]
                        prev_updated = False
                        for child in prev_view.children:
                            if getattr(child, "custom_id", "") == "good_bot_btn":
                                if not child.disabled:
                                    child.disabled = True
                                    child.style = discord.ButtonStyle.secondary
                                    child.label = "Good Bot!"
                                    prev_updated = True
                        if prev_updated:
                            try:
                                old_msg = await message.channel.fetch_message(prev_msg_id)
                                await old_msg.edit(view=prev_view)
                            except: pass

                    sent_message = None
                    if len(response_text) > 2000:
                        from io import BytesIO
                        file = discord.File(BytesIO(response_text.encode()), filename="response.txt")
                        sent_message = await message.reply("(Response too long, see file)", file=file, view=view, mention_author=False)
                    else:
                        sent_message = await message.reply(response_text, view=view, mention_author=False)
                    
                    if sent_message:
                        client.active_views[sent_message.id] = view
                        client.last_bot_message_id[message.channel.id] = sent_message.id
                        client.loop.create_task(client.suppress_embeds_later(sent_message, delay=5))

                except discord.HTTPException as e:
                    if e.code == 50035 or e.status == 400 or e.status == 404:
                        print(f"DEBUG: Trigger message {message.id} deleted during processing. Ignored.")
                    else:
                        print(f"DEBUG: Failed to reply: {e}")

    finally:
        if message.id in client.processing_locks:
            client.processing_locks.remove(message.id)

client.run(BOT_TOKEN)
