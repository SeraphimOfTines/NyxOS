import aiohttp
import re
import json
import asyncio
from datetime import datetime
import config
import helpers
import memory_manager
import logging
import rate_limiter
from collections import OrderedDict

logger = logging.getLogger("Services")

class APIService:
    def __init__(self):
        self.http_session = None
        self.db_pool = None
        self.pk_user_cache = OrderedDict()   
        self.pk_message_cache = OrderedDict()
        self.pk_proxy_tags = OrderedDict()   
        self.my_system_members = set()  
        self.limiter = rate_limiter.limiter 
        self.MAX_CACHE_SIZE = 500

    async def start(self):
        self.http_session = aiohttp.ClientSession()
        
        if config.USE_LOCAL_PLURALKIT and hasattr(config, 'PLURALKIT_DB_URI') and config.PLURALKIT_DB_URI:
            try:
                import asyncpg
                self.db_pool = await asyncpg.create_pool(config.PLURALKIT_DB_URI)
                logger.info("Connected to PluralKit Database.")
            except Exception as e:
                logger.error(f"Failed to connect to PK DB: {e}")
        
        await self.fetch_my_system_data()
        logger.info("APIService started.")

    async def close(self):
        if self.http_session:
            try:
                await self.http_session.close()
            except TypeError:
                pass 
        if self.db_pool:
            await self.db_pool.close()
        logger.info("APIService closed.")

    # --- PLURALKIT ---

    async def fetch_my_system_data(self):
        systems_to_fetch = [config.MY_SYSTEM_ID]
        if getattr(config, 'SECONDARY_SYSTEM_ID', None):
            systems_to_fetch.append(config.SECONDARY_SYSTEM_ID)

        for sys_id in systems_to_fetch:
            if not sys_id: continue
            try:
                url = config.PLURALKIT_SYSTEM_MEMBERS.format(sys_id)
                # If using local PK, we might need to use official API for the secondary system 
                # IF the secondary system is not in the local DB/Mirror.
                # But for simplicity, we trust the configured API first.
                # If config.PLURALKIT_SYSTEM_MEMBERS uses local, we try local.
                # If that fails (404), we should try official? 
                # The requirements say "switch to official... for whatever data is needed".
                # So yes, we should probably use a robust fetch here too.
                
                # We can reuse a robust fetch pattern here, but let's keep it inline for now or use a helper if I make one.
                # Since I haven't made the helper yet, I will just use the current session with fallback logic logic inline 
                # or assumes the configured API works for now, but the prompt implies general robustness.
                
                # Let's implement the fallback logic here too.
                async def fetch_members(target_url):
                    async with self.http_session.get(target_url) as resp:
                        if resp.status == 200:
                            members = await resp.json()
                            for m in members:
                                if 'name' in m: self.my_system_members.add(m['name'])
                                if 'display_name' in m and m['display_name']: self.my_system_members.add(m['display_name'])
                            return True
                        return False

                success = await fetch_members(url)
                if not success and config.USE_LOCAL_PLURALKIT:
                     # Fallback to Official
                     logger.info(f"Local fetch failed for system {sys_id}. Trying Official API...")
                     official_url = f"https://api.pluralkit.me/v2/systems/{sys_id}/members"
                     await fetch_members(official_url)

            except Exception as e:
                logger.warning(f"Error fetching system data for {sys_id}: {e}")

    async def check_local_pk_system(self, user_id):
        """Checks if a user has a system. Tries local DB first, then falls back to full API lookup."""
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Check if uid exists in accounts table and has a system linked
                    val = await conn.fetchval("SELECT system FROM accounts WHERE uid = $1", user_id)
                    if val is not None: return True
            except Exception as e:
                logger.error(f"Local PK Check Failed: {e}")
                # Fallthrough to API logic below
        
        # Fallback to API (uses Cache + Redundancy)
        data = await self.get_pk_user_data(user_id)
        return data is not None

    async def _fetch_pk_user_api(self, url, user_id):
        """Helper to fetch user data from a specific PK API URL."""
        try:
            async with self.http_session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {'system_id': data.get('id'), 'tag': data.get('tag')}
                    
                    # Cache Success
                    self.pk_user_cache[user_id] = result
                    if len(self.pk_user_cache) > self.MAX_CACHE_SIZE:
                        self.pk_user_cache.popitem(last=False)
                    return result
                elif resp.status == 404:
                    return None # Not found here
                else:
                    logger.warning(f"PK User API Error {resp.status} from {url}")
                    return None
        except Exception as e:
            logger.warning(f"PK User API Exception for {url}: {e}")
            return None

    async def get_pk_user_data(self, user_id):
        # 1. Try DB if Local
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT s.hid, s.tag 
                        FROM accounts a 
                        JOIN systems s ON a.system = s.id 
                        WHERE a.uid = $1
                    """, user_id)
                    if row:
                        result = {'system_id': row['hid'], 'tag': row['tag']}
                        
                        # Cache Logic
                        if user_id in self.pk_user_cache:
                            self.pk_user_cache.move_to_end(user_id)
                        else:
                            self.pk_user_cache[user_id] = result
                            if len(self.pk_user_cache) > self.MAX_CACHE_SIZE:
                                self.pk_user_cache.popitem(last=False)
                                
                        return result
            except Exception as e:
                logger.error(f"PK DB User Lookup Error: {e}")

        # 2. Check Cache
        if user_id in self.pk_user_cache:
            self.pk_user_cache.move_to_end(user_id)
            return self.pk_user_cache[user_id]

        # 3. Try Configured API
        url = config.PLURALKIT_USER_API.format(user_id)
        result = await self._fetch_pk_user_api(url, user_id)
        
        # 4. Fallback to Official API
        # If result is None (404 or Error) AND we are using Local PK, try Official
        if result is None and config.USE_LOCAL_PLURALKIT:
             # We can't easily distinguish 404 (User doesn't exist) vs 404 (User not in Local Mirror).
             # So we try Official just in case.
             logger.info(f"Local PK User lookup failed for {user_id}. Trying Official API...")
             official_url = f"https://api.pluralkit.me/v2/users/{user_id}"
             result = await self._fetch_pk_user_api(official_url, user_id)

        # Cache the final None result if we really found nothing (to prevent spamming)
        if result is None:
             self.pk_user_cache[user_id] = None
             if len(self.pk_user_cache) > self.MAX_CACHE_SIZE:
                  self.pk_user_cache.popitem(last=False)
        
        return result

    async def get_system_proxy_tags(self, system_id):
        if system_id in self.pk_proxy_tags:
            self.pk_proxy_tags.move_to_end(system_id)
            return self.pk_proxy_tags[system_id]

        url = config.PLURALKIT_SYSTEM_MEMBERS.format(system_id)
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
                    if len(self.pk_proxy_tags) > self.MAX_CACHE_SIZE:
                        self.pk_proxy_tags.popitem(last=False)
                        
        except Exception as e:
            logger.warning(f"Error fetching proxy tags: {e}")
        return tags

    async def _fetch_pk_message_api(self, url, message_id):
        """Helper to fetch message data from a specific PK API URL."""
        for attempt in range(3):
            try:
                async with self.http_session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        member_name = data.get('member', {}).get('name')
                        member_display = data.get('member', {}).get('display_name')
                        final_name = member_display if member_display else member_name
                        
                        system_data = data.get('system', {})
                        system_id = system_data.get('id')
                        system_name = system_data.get('name')
                        system_tag = system_data.get('tag')
                        sender_id = data.get('sender') 
                        
                        description = data.get('member', {}).get('description', "")
                        if description:
                            description = description.replace('[', '(').replace(']', ')')
                        
                        result = (final_name, system_id, system_name, system_tag, sender_id, description)
                        
                        # Update Cache
                        self.pk_message_cache[message_id] = result
                        if len(self.pk_message_cache) > self.MAX_CACHE_SIZE:
                            self.pk_message_cache.popitem(last=False)

                        return result
                    elif resp.status == 429:
                        logger.warning(f"PK Rate Limit (429) on attempt {attempt+1} for {url}. Retrying...")
                        await asyncio.sleep(1 * (attempt + 1))
                    elif resp.status == 404:
                        # Not a PK message (or not found in this instance)
                        return None
                    else:
                        logger.warning(f"PK API Error {resp.status} on attempt {attempt+1} for {url}.")
            except Exception as e:
                logger.warning(f"PK Message API Exception on attempt {attempt+1} for {url}: {e}")
                await asyncio.sleep(1)
        return None

    async def get_pk_message_data(self, message_id):
        # 0. Check Cache
        if message_id in self.pk_message_cache:
            self.pk_message_cache.move_to_end(message_id)
            return self.pk_message_cache[message_id]

        # 1. Try DB if Local
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Join messages -> members -> systems
                    # 'mid' is commonly the Discord Message ID column in PK
                    row = await conn.fetchrow("""
                        SELECT 
                            m.sender AS sender_id,
                            mem.name,
                            mem.display_name,
                            mem.description,
                            s.hid AS system_id,
                            s.name AS system_name,
                            s.tag AS system_tag
                        FROM messages m
                        LEFT JOIN members mem ON m.member = mem.id
                        LEFT JOIN systems s ON mem.system = s.id
                        WHERE m.mid = $1
                    """, message_id)
                    
                    if row:
                        final_name = row['display_name'] if row['display_name'] else row['name']
                        desc = row['description']
                        if desc: desc = desc.replace('[', '(').replace(']', ')')
                        
                        result = (
                            final_name, 
                            row['system_id'], 
                            row['system_name'], 
                            row['system_tag'], 
                            row['sender_id'], 
                            desc
                        )
                        
                        # Update Cache
                        self.pk_message_cache[message_id] = result
                        if len(self.pk_message_cache) > self.MAX_CACHE_SIZE:
                            self.pk_message_cache.popitem(last=False)
                        
                        return result
            except Exception as e:
                logger.error(f"PK DB Message Lookup Error: {e}")

        # 2. Try Configured API
        url = config.PLURALKIT_MESSAGE_API.format(message_id)
        result = await self._fetch_pk_message_api(url, message_id)

        # 3. Fallback to Official API
        if result is None and config.USE_LOCAL_PLURALKIT:
             logger.info(f"Local PK Message lookup failed for {message_id}. Trying Official API...")
             official_url = f"https://api.pluralkit.me/v2/messages/{message_id}"
             result = await self._fetch_pk_message_api(official_url, message_id)

        if result is None:
             return None, None, None, None, None, None
        
        return result

    # --- WEB SEARCH ---

    async def generate_search_queries(self, user_prompt, history_messages, force_search=False):
        if not config.KAGI_API_TOKEN: return None

        # Double check sanitization
        clean_prompt = user_prompt.replace("&web", "").strip()

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
            f"{('4. The user has EXPLICITLY requested a search (&web). You MUST generate queries.' if force_search else '4. If NO search is needed (casual chat, opinions), output exactly: NO_SEARCH')}\n"
        )

        user_content = f"### CONTEXT ###\n{context_str}\n\n### CURRENT REQUEST ###\n{clean_prompt}\n\n### GENERATE QUERIES ###"

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
            async with self.http_session.post(config.LM_STUDIO_URL, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data['choices'][0]['message']['content'].strip()
                    if "NO_SEARCH" in content and not force_search: return []
                    queries = [q.strip() for q in content.split('\n') if q.strip()]
                    clean_queries = []
                    for q in queries:
                        # Remove numbers, dashes, or asterisks at start
                        q = re.sub(r'^\d+\.\s*|[-*]\s*', '', q).strip()
                        # Remove &web if LLM hallucinates it back in
                        q = q.replace("&web", "").strip()
                        if q.lower() != user_prompt.lower(): clean_queries.append(q)
                    if force_search and not clean_queries: return [user_prompt]
                    # Return up to 3 queries maximum to avoid spamming Kagi
                    return clean_queries[:3]
        except Exception as e:
            logger.error(f"Query Generation Failed: {e}")
            if force_search: return [user_prompt]
        return []

    async def search_kagi(self, query):
        if not config.KAGI_API_TOKEN: return "Error: Config missing."
        logger.info(f"[KAGI] Searching for: '{query}'")
        headers = {"Authorization": f"Bot {config.KAGI_API_TOKEN}"}
        params = {"q": query, "limit": 6} 
        try:
            async with self.http_session.get(config.KAGI_SEARCH_URL, headers=headers, params=params) as resp:
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

    # --- LLM INFERENCE ---

    async def query_lm_studio(self, user_prompt, username, identity_suffix, history_messages, channel_obj, image_data_uri=None, member_description=None, search_context=None, reply_context_str="", system_prompt_override=None):
        
        # Use override if provided (even empty string)
        if system_prompt_override is not None:
            formatted_system_prompt = system_prompt_override
        else:
            # --- STANDARD TEMPLATE LOGIC ---
            date_str, time_str = helpers.get_system_time()
            
            # Dynamically construct template from latest config values
            raw_system_prompt = config.SYSTEM_PROMPT
            
            # Determine Injected Prompt based on Channel Type
            is_terminal = hasattr(channel_obj, 'name') and channel_obj.name == 'terminal'
            
            if is_terminal and config.INJECTED_TERMINAL_PROMPT:
                raw_system_prompt += f"\n\n{config.INJECTED_TERMINAL_PROMPT}"
            elif config.INJECTED_PROMPT:
                raw_system_prompt += f"\n\n{config.INJECTED_PROMPT}"

            # Check if prompt uses time placeholders
            has_time_placeholder = "{{CURRENT_DATETIME}}" in raw_system_prompt
            
            base_prompt = raw_system_prompt \
                .replace("{{USER_NAME}}", "the people in this chatroom") \
                .replace("{{Seraphim}}", "Seraphim") \
                .replace("{{CONTEXT}}", "") \
                .replace("{{CURRENT_WEEKDAY}}", datetime.now().strftime("%A")) \
                .replace("{{CURRENT_DATETIME}}", f"{date_str}, {time_str}")

            # Only prepend header if the user didn't use the placeholder
            if not has_time_placeholder:
                 time_header = f"Current Date: {date_str}\nCurrent Time: {time_str}\n\n"
                 base_prompt = time_header + base_prompt
                
            if member_description:
                clean_desc = member_description.replace('[', '(').replace(']', ')')
                base_prompt += f"\n\n(Context: The user '{username}' has the following description: {clean_desc})"

            if search_context:
                base_prompt += f"\n\n<search_results>\nThe user requested a web search. Here are the results:\n{search_context}\n</search_results>\n\nINSTRUCTION: Use the above search results to answer the user's request accurately. YOU MUST CITE SOURCES. Use the format: [Source Title](URL) at the end of the relevant sentence or paragraph."

            formatted_system_prompt = base_prompt

        display_name_for_ai = f"{username}{identity_suffix}"

        raw_messages = [{"role": "system", "content": formatted_system_prompt}]
        
        # --- HISTORY CLEANUP ---
        cleaned_history = []
        for i, msg in enumerate(history_messages):
            content_str = str(msg.get('content', ''))
            if "I'm back online! Hi!" in content_str: continue
            
            cleaned_history.append(msg)
        
        while len(cleaned_history) > 0 and cleaned_history[0].get('role') == 'assistant':
            cleaned_history.pop(0)
            
        raw_messages.extend(cleaned_history)

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
                if isinstance(last_msg['content'], str):
                    last_msg['content'] = [{"type": "text", "text": last_msg['content']}]
                
                current_list = msg['content']
                if isinstance(current_list, str):
                    current_list = [{"type": "text", "text": current_list}]
                
                # Insert a newline separator before appending new content
                if last_msg['content'] and last_msg['content'][-1]['type'] == 'text':
                    last_msg['content'][-1]['text'] += "\n"
                else:
                    last_msg['content'].append({"type": "text", "text": "\n"})

                last_msg['content'].extend(current_list)
            else:
                merged_messages.append(msg)

        if len(merged_messages) > 1 and merged_messages[1]['role'] == 'assistant':
            merged_messages.pop(1)

        # Log to Memory Buffer
        await memory_manager.write_context_buffer(merged_messages, channel_obj.id, channel_obj.name)
        
        try:
            return await self._send_payload(merged_messages)
        except Exception as e:
            if "400" in str(e) or "base64" in str(e).lower():
                logger.error(f"Vision Payload Failed. Error: {e}. Retrying request without images...")
                text_only_messages = self._strip_images(merged_messages)
                return await self._send_payload(text_only_messages)
            raise e

    async def _send_payload(self, messages):
        headers = {"Content-Type": "application/json"}
        
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
        
        payload = {
            "messages": cleaned_messages,
            "temperature": config.MODEL_TEMPERATURE,
            "max_tokens": -1,
            "stream": False
        }
        
        print(f"\n--- DEBUG PAYLOAD --- Roles: {'. '.join([m.get('role', 'unknown') for m in cleaned_messages])}")
        logger.info(f"Sending request to LM Studio: {config.LM_STUDIO_URL}")

        async with self.http_session.post(config.LM_STUDIO_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                content = data['choices'][0]['message']['content']
                # Strip ALL '#' characters as requested to prevent markdown header issues
                # REMOVED: This breaks URL anchors. Handled in helpers.sanitize_llm_response instead.
                return content
            else:
                error_text = await resp.text()
                logger.error(f"LM Studio Error ({resp.status}): {error_text}")
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

    async def get_chat_response(self, messages):
        """
        Simplified wrapper for direct chat completions (e.g., used by Backup Manager).
        Allows passing a raw list of messages directly to the configured LLM.
        """
        return await self._send_payload(messages)

# Global Instance
service = APIService()
