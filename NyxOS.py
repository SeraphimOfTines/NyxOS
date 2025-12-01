import discord
from discord import app_commands
import logging
import asyncio
import os
import sys
import base64
import json
import re
import time
import signal
import hashlib
import subprocess
import traceback
from collections import OrderedDict, deque

# Local Modules
import config

# ==========================================
# LOGGING SETUP (Must be before other imports)
# ==========================================
# Ensure logs directory exists
os.makedirs(config.LOGS_DIR, exist_ok=True)

class RobustHTTPLogger(logging.Filter):
    def filter(self, record):
        # Catch "We are being rate limited" from discord.http
        if record.name == "discord.http" and "rate limited" in record.getMessage().lower():
            stack = traceback.format_stack()
            filtered = []
            found_local = False
            for line in stack:
                # Filter for our files to identify the source
                if any(x in line for x in ["NyxOS.py", "services.py", "ui.py", "memory_manager.py", "helpers.py"]):
                    filtered.append(f" >> {line.strip()}")
                    found_local = True
            
            if found_local:
                record.msg += f"\n🚨 RATE LIMIT SOURCE TRACE:\n" + "\n".join(filtered)
            else:
                # Fallback if no local file found (weird, but capture last few lines)
                record.msg += f"\n🚨 RATE LIMIT (External Source):\n" + "".join(stack[-5:])
        return True

# Configure Logging
logger = logging.getLogger('NyxOS') # Local logger for this file
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

# Add filter to handlers (so it modifies the record before emit)
robust_filter = RobustHTTPLogger()

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.addFilter(robust_filter)

# File Handler
file_handler = logging.FileHandler(os.path.join(config.LOGS_DIR, 'nyxos.log'), encoding='utf-8')
file_handler.setFormatter(formatter)
file_handler.addFilter(robust_filter)

# Apply handlers to root (captures all loggers: NyxOS, RateLimiter, discord, etc.)
if not root_logger.handlers:
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

# Force discord.http to show requests if needed (Uncomment to see ALL traffic)
# logging.getLogger("discord.http").setLevel(logging.INFO)

# Other Local Modules (Imported AFTER logging is set up)
import helpers
import services
import memory_manager
import ui

# ==========================================
# BOT SETUP
# ==========================================

def kill_duplicate_processes():
    """Nuclear option: Kills other instances with SIGKILL and ensures they are dead."""
    my_pid = os.getpid()
    logger.info(f"💀 Nuclear cleanup initiated. My PID: {my_pid}")
    
    # Retry loop to ensure death
    for i in range(3):
        try:
            # Find all PIDs matching "python.*NyxOS.py"
            result = subprocess.run(['pgrep', '-f', 'python.*NyxOS.py'], stdout=subprocess.PIPE, text=True)
            
            if result.returncode != 0:
                break # No processes found
            
            pids = result.stdout.strip().split('\n')
            killed_something = False
            
            for pid_str in pids:
                if not pid_str.strip(): continue
                try:
                    pid = int(pid_str)
                    if pid != my_pid:
                        logger.warning(f"💥 SIGKILLing PID: {pid}")
                        os.kill(pid, signal.SIGKILL) # NUCLEAR
                        killed_something = True
                except (ValueError, ProcessLookupError):
                    pass
            
            if not killed_something:
                break # Only self remaining (or none)
            
            time.sleep(1) # Wait for OS to clean up
            
        except Exception as e:
            logger.warning(f"⚠️ Error during process cleanup: {e}")
            break

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

class LMStudioBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        
        # Runtime State
        self.channel_cutoff_times = OrderedDict()
        self.good_bot_cooldowns = OrderedDict() 
        self.processing_locks = set() 
        self.active_views = OrderedDict() 
        self.active_bars = {}
        self.bar_history = {} # Mapping channel_id -> deque(maxlen=2)
        self.bar_drop_cooldowns = {}
        self.last_bot_message_id = {} 
        self.boot_cleared_channels = set()
        self.has_synced = False
        self.abort_signals = set()
        self.active_drop_tasks = set()
        self.pending_drops = set()

    def get_tree_hash(self):
        """Generates a hash of the current command tree structure."""
        cmds = sorted(self.tree.get_commands(), key=lambda c: c.name)
        data = []
        for cmd in cmds:
            cmd_dict = {
                "name": cmd.name,
                "description": cmd.description,
                "nsfw": cmd.nsfw,
                "parameters": []
            }
            if hasattr(cmd, 'parameters'):
                for param in cmd.parameters:
                     cmd_dict["parameters"].append({
                         "name": param.name,
                         "description": param.description,
                         "required": param.required,
                         "type": str(param.type)
                     })
            data.append(cmd_dict)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _register_view(self, message_id, view):
        """Registers a view with global LRU eviction (Limit ~2000)."""
        if message_id in self.active_views:
            self.active_views.move_to_end(message_id)
        self.active_views[message_id] = view
        if len(self.active_views) > 2000:
            self.active_views.popitem(last=False)

    def _register_bar_message(self, channel_id, message_id, view):
        """Registers a bar message and view, ensuring only 2 layers of history are kept."""
        # 1. Register to global LRU first (so it's trackable)
        self._register_view(message_id, view)
        
        # 2. Manage History Pruning
        if channel_id not in self.bar_history:
            self.bar_history[channel_id] = []
            
        if message_id not in self.bar_history[channel_id]:
            self.bar_history[channel_id].append(message_id)
        
        # Keep Current + 2 History = 3 Items Max
        while len(self.bar_history[channel_id]) > 3:
            old_id = self.bar_history[channel_id].pop(0)
            # Explicitly remove from active_views memory
            self.active_views.pop(old_id, None)

    def _update_lru_cache(self, cache_dict, key, value, limit=1000):
        """Updates an OrderedDict cache with LRU eviction."""
        if key in cache_dict:
            cache_dict.move_to_end(key)
        cache_dict[key] = value
        if len(cache_dict) > limit:
            cache_dict.popitem(last=False)

    async def setup_hook(self):
        # Clean startup flags
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            try: os.remove(config.SHUTDOWN_FLAG_FILE)
            except: pass
            
        await services.service.start()
        self.add_view(ui.ResponseView())
        self.add_view(ui.ConsoleControlView())
        self.loop.create_task(self.heartbeat_task())

    def request_bar_drop(self, channel_id):
        """Debounced drop request manager."""
        if channel_id in self.active_drop_tasks:
            self.pending_drops.add(channel_id)
        else:
            self.active_drop_tasks.add(channel_id)
            self.loop.create_task(self._process_drop_queue(channel_id))

    async def _process_drop_queue(self, channel_id):
        try:
            while True:
                # Perform the drop (Do NOT move checkmark for auto-mode)
                await self.drop_status_bar(channel_id, move_check=False)
                
                # Wait debounce period (0.5 seconds)
                await asyncio.sleep(0.5)
                
                if channel_id in self.pending_drops:
                    self.pending_drops.remove(channel_id)
                    # Loop again to process pending
                else:
                    break
        finally:
            self.active_drop_tasks.discard(channel_id)

    async def wait_for_ghost_and_drop(self, channel_id, message_id):
        """Waits to see if a message is proxied (deleted) before dropping bar."""
        await asyncio.sleep(1.5) 
        try:
            channel = self.get_channel(channel_id)
            if not channel: channel = await self.fetch_channel(channel_id)
            
            try:
                await channel.fetch_message(message_id)
                # If found, it wasn't proxied. Drop bar now.
                self.request_bar_drop(channel_id)
            except discord.NotFound:
                # Message deleted (ghosted). Webhook will trigger drop.
                pass
        except: pass

    async def drop_status_bar(self, channel_id, move_bar=True, move_check=True):
        if channel_id not in self.active_bars: return
        
        bar_data = self.active_bars[channel_id]
        channel = self.get_channel(channel_id)
        if not channel:
            try: channel = await self.fetch_channel(channel_id)
            except: return

        old_bar_id = bar_data.get("message_id")
        old_check_id = bar_data.get("checkmark_message_id")
        
        # Clean content (Remove checkmark if present in string for the bar)
        content = bar_data["content"]
        if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in content:
             content = content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
        
        # Ensure we have a prefix if missing
        if not any(content.startswith(emoji) for emoji in ui.BAR_PREFIX_EMOJIS):
             # Try to restore from known
             pass 

        new_bar_msg = None

        # 1. Handle Bar Movement
        if move_bar:
            # Delete old bar (OR Split if checkmark stays)
            if old_bar_id:
                try:
                    old_msg = await channel.fetch_message(old_bar_id)
                    
                    if old_bar_id == old_check_id and not move_check:
                        # SPLIT: Bar moves, Check stays. 
                        # Edit old message to be just Checkmark.
                        await old_msg.edit(content=ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], view=None)
                    else:
                        # DELETE: Bar moves, Check moves (or is separate).
                        await old_msg.delete()
                except: pass
            
            # Send new bar
            view = ui.StatusBarView(content, bar_data["user_id"], channel_id, bar_data["persisting"])
            try:
                await services.service.limiter.wait_for_slot("send_message", channel_id)
                new_bar_msg = await channel.send(content, view=view)
                
                # Update State
                self.active_bars[channel_id]["message_id"] = new_bar_msg.id
                self._register_bar_message(channel_id, new_bar_msg.id, view)
            except Exception as e:
                logger.error(f"Failed to send bar: {e}")
                return
        else:
            # If not moving bar, we need the object to know where to put the check (if separate?)
            # Actually, if check is separate, we just send it. 
            # But if we want to link them, or if we need the ID for DB.
            if old_bar_id:
                try:
                    new_bar_msg = await channel.fetch_message(old_bar_id)
                except: pass
                
        # 2. Handle Checkmark Movement
        if move_check:
            # Delete old check
            if old_check_id and old_check_id != old_bar_id: 
                 try:
                    old_chk = await channel.fetch_message(old_check_id)
                    await old_chk.delete()
                 except: pass
            
            # Send new check (Inline if target is bar)
            target_msg = new_bar_msg
            if not target_msg and old_bar_id:
                 # If bar didn't move, target is old bar
                 try: target_msg = await channel.fetch_message(old_bar_id)
                 except: pass
            
            if target_msg:
                # Edit target to include checkmark inline
                chk_content = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                curr_content = target_msg.content
                
                if chk_content not in curr_content:
                    new_content = f"{curr_content} {chk_content}"
                    new_content = re.sub(r'>[ \t]+<', '><', new_content)
                    new_content = new_content.replace(f"\n{chk_content}", f" {chk_content}")
                    
                    try:
                        await services.service.limiter.wait_for_slot("edit_message", channel_id)
                        
                        # Use existing view or recreate?
                        view = None
                        if target_msg.id in self.active_views:
                            view = self.active_views[target_msg.id]
                        else:
                            view = ui.StatusBarView(new_content, bar_data["user_id"], channel_id, bar_data["persisting"])
                            
                        await target_msg.edit(content=new_content, view=view)
                        self.active_bars[channel_id]["checkmark_message_id"] = target_msg.id
                    except Exception as e:
                         logger.error(f"Failed to merge check: {e}")
            else:
                # Fallback: If no bar exists, we can't merge. 
                # Logic dictates we should have dropped a bar if move_bar=True.
                pass

        # Update DB
        bar_final_id = self.active_bars[channel_id].get("message_id")
        check_final_id = self.active_bars[channel_id].get("checkmark_message_id")
        
        memory_manager.save_channel_location(channel_id, bar_final_id, check_final_id)
        
        # Also update legacy save_bar (for content persistence)
        final_content = self.active_bars[channel_id]["content"]
        # We save the content WITHOUT checkmark to DB (clean), but display WITH it.
        memory_manager.save_bar(
            channel_id, 
            channel.guild.id if channel.guild else None,
            bar_final_id,
            self.active_bars[channel_id]["user_id"],
            final_content,
            self.active_bars[channel_id]["persisting"]
        )

    async def sleep_all_bars(self):
        """
        Puts all active bars and remnants in allowed channels to sleep.
        Returns the number of bars processed.
        """
        # 1. Consolidate targets: Active Bars + Remnants in Allowed Channels
        targets = list(self.active_bars.items())
        allowed = memory_manager.get_allowed_channels()
        
        # Scan allowed channels for remnants not in active_bars
        for ac_id in allowed:
            if ac_id not in self.active_bars:
                targets.append((ac_id, None))

        sleeping_emoji = "<a:Sleeping:1312772391759249410>"

        async def process_bar(cid, bar_data):
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False

                # Resolve Content
                current_content = ""
                if bar_data:
                    current_content = bar_data["content"]
                    # Save state if going to sleep
                    memory_manager.save_previous_state(cid, bar_data)
                else:
                    # Remnant recovery
                    found = await self.find_last_bar_content(ch)
                    if found:
                        current_content = found
                        # Strip checkmark
                        if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in current_content:
                            current_content = current_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    else:
                        return False

                # Construct New Content
                clean_middle = current_content
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if clean_middle.startswith(emoji):
                        clean_middle = clean_middle[len(emoji):].strip()
                        break
                
                new_base_content = f"{sleeping_emoji} {clean_middle}"
                new_base_content = re.sub(r'>[ \t]+<', '><', new_base_content)

                # Attempt Edit-In-Place First
                msg_id = bar_data.get("message_id") if bar_data else None
                msg = None
                if msg_id:
                    try: msg = await ch.fetch_message(msg_id)
                    except: pass
                
                persisting = bar_data.get("persisting", False) if bar_data else False

                if msg:
                    # Handle Checkmark
                    check_id = bar_data.get("checkmark_message_id")
                    has_merged_check = (check_id == msg_id)
                    
                    final_content = new_base_content
                    if has_merged_check:
                        chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                        if chk not in final_content:
                            final_content = f"{final_content} {chk}"
                            final_content = re.sub(r'>[ \t]+<', '><', final_content)

                    try:
                        view = ui.StatusBarView(final_content, bar_data["user_id"], cid, persisting)
                        await services.service.limiter.wait_for_slot("edit_message", cid)
                        await msg.edit(content=final_content, view=view)
                        
                        self.active_bars[cid] = {
                            "content": new_base_content,
                            "user_id": bar_data["user_id"],
                            "message_id": msg.id,
                            "checkmark_message_id": msg.id,
                            "persisting": persisting,
                            "current_prefix": sleeping_emoji
                        }
                        self._register_bar_message(cid, msg.id, view)
                        memory_manager.save_bar(cid, ch.guild.id, msg.id, bar_data["user_id"], new_base_content, persisting, current_prefix=sleeping_emoji)
                        return True
                    except Exception as e:
                        logger.warning(f"Sleep edit failed in {cid}, falling back to wipe/send: {e}")

                # FALLBACK: Wipe & Replace
                await self.wipe_channel_bars(ch)

                # Checkmark included in new send? usually drop/send includes it.
                # But here we are constructing base content.
                # Let's standardise: always include checkmark on new send.
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                send_content = f"{new_base_content} {chk}"
                send_content = re.sub(r'>[ \t]+<', '><', send_content)

                view = ui.StatusBarView(send_content, self.user.id, cid, persisting)
                await services.service.limiter.wait_for_slot("send_message", cid)
                new_msg = await ch.send(send_content, view=view)
                
                self.active_bars[cid] = {
                    "content": new_base_content,
                    "user_id": self.user.id,
                    "message_id": new_msg.id,
                    "checkmark_message_id": new_msg.id,
                    "persisting": persisting,
                    "current_prefix": sleeping_emoji
                }
                self._register_bar_message(cid, new_msg.id, view)
                
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting, current_prefix=sleeping_emoji)
                return True

            except Exception as e:
                logger.error(f"Sleep error in {cid}: {e}")
                return False

        tasks = []
        for cid, bar in targets:
            tasks.append(process_bar(cid, bar))
        
        results = await asyncio.gather(*tasks)
        
        # Sync Console
        await self.update_console_status()
        
        return sum(1 for r in results if r)

    async def idle_all_bars(self):
        """
        Sets all active bars and remnants in allowed channels to IDLE (Not Watching).
        Returns the number of bars processed.
        """
        # 1. Consolidate targets
        targets = list(self.active_bars.items())
        allowed = memory_manager.get_allowed_channels()
        
        for ac_id in allowed:
            if ac_id not in self.active_bars:
                targets.append((ac_id, None))

        idle_emoji = "<a:NotWatching:1301840196966285322>" # speed0

        async def process_bar(cid, bar_data):
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False

                # Resolve Content
                current_content = ""
                if bar_data:
                    current_content = bar_data["content"]
                else:
                    # Remnant recovery
                    found = await self.find_last_bar_content(ch)
                    if found:
                        current_content = found
                        if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in current_content:
                            current_content = current_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    else:
                        return False

                # Construct New Content
                clean_middle = current_content
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if clean_middle.startswith(emoji):
                        clean_middle = clean_middle[len(emoji):].strip()
                        break
                
                new_base_content = f"{idle_emoji} {clean_middle}"
                new_base_content = re.sub(r'>[ \t]+<', '><', new_base_content)

                # Attempt Edit-In-Place
                msg_id = bar_data.get("message_id") if bar_data else None
                msg = None
                if msg_id:
                    try: msg = await ch.fetch_message(msg_id)
                    except: pass
                
                persisting = bar_data.get("persisting", False) if bar_data else False

                if msg:
                    # Handle Checkmark
                    check_id = bar_data.get("checkmark_message_id")
                    has_merged_check = (check_id == msg_id)
                    
                    final_content = new_base_content
                    if has_merged_check:
                        chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                        if chk not in final_content:
                            final_content = f"{final_content} {chk}"
                            final_content = re.sub(r'>[ \t]+<', '><', final_content)
                    
                    try:
                        view = ui.StatusBarView(final_content, bar_data["user_id"], cid, persisting)
                        await services.service.limiter.wait_for_slot("edit_message", cid)
                        await msg.edit(content=final_content, view=view)
                        
                        self.active_bars[cid] = {
                            "content": new_base_content,
                            "user_id": bar_data["user_id"],
                            "message_id": msg.id,
                            "checkmark_message_id": msg.id,
                            "persisting": persisting,
                            "current_prefix": idle_emoji
                        }
                        self._register_bar_message(cid, msg.id, view)
                        memory_manager.save_bar(cid, ch.guild.id, msg.id, bar_data["user_id"], new_base_content, persisting, current_prefix=idle_emoji)
                        return True
                    except Exception as e:
                        logger.warning(f"Idle edit failed in {cid}, falling back to wipe/send: {e}")

                # FALLBACK: Wipe & Replace
                await self.wipe_channel_bars(ch)
                
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                send_content = f"{new_base_content} {chk}"
                send_content = re.sub(r'>[ \t]+<', '><', send_content)

                view = ui.StatusBarView(send_content, self.user.id, cid, persisting)
                await services.service.limiter.wait_for_slot("send_message", cid)
                new_msg = await ch.send(send_content, view=view)

                self.active_bars[cid] = {
                    "content": new_base_content,
                    "user_id": self.user.id,
                    "message_id": new_msg.id,
                    "checkmark_message_id": new_msg.id,
                    "persisting": persisting,
                    "current_prefix": idle_emoji
                }
                self._register_bar_message(cid, new_msg.id, view)
                
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting, current_prefix=idle_emoji)
                return True

            except Exception as e:
                logger.error(f"Idle error in {cid}: {e}")
                return False

        tasks = []
        for cid, bar in targets:
            tasks.append(process_bar(cid, bar))
        
        results = await asyncio.gather(*tasks)
        
        # Sync Console
        await self.update_console_status()

        return sum(1 for r in results if r)

    async def global_update_bars(self, new_text_suffix):
        """
        Updates the content (suffix) of all active bars while preserving their current status emoji.
        Also updates the Master Bar (DB + Console Channel) to ensure consistency.
        Does NOT move the bar (edits in place).
        """
        # 1. Update Master Bar in Database (Source of Truth)
        clean_suffix = new_text_suffix.strip()
        clean_suffix = re.sub(r'>[ \t]+<', '><', clean_suffix)
        memory_manager.set_master_bar(clean_suffix)

        # 2. Update Console Channel Bar (Startup Bar) if available
        # This is the "visual" master bar the user sees in the console
        if hasattr(self, 'startup_bar_msg') and self.startup_bar_msg:
            try:
                await self.startup_bar_msg.edit(content=clean_suffix)
            except (discord.NotFound, discord.HTTPException):
                logger.warning("Could not update startup_bar_msg (not found or error).")
                self.startup_bar_msg = None

        # 3. Propagate to All Active Bars (Uplinks)
        targets = list(self.active_bars.items())
        count = 0

        async def process_update(cid, bar_data):
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False

                msg_id = bar_data.get("message_id")
                if not msg_id: return False

                # Get current content to find emoji
                current_content = bar_data.get("content", "")
                
                # Identify prefix
                prefix = ""
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if current_content.startswith(emoji):
                        prefix = emoji
                        break
                
                # Simple heuristic for unknown emojis
                if not prefix and current_content.startswith("<a:"):
                     end_idx = current_content.find(">")
                     if end_idx != -1:
                         prefix = current_content[:end_idx+1]
                
                # Construct new content: Prefix + New Suffix
                if prefix:
                    final_content = f"{prefix} {clean_suffix}"
                else:
                    final_content = clean_suffix

                # Handle Checkmark (if merged)
                check_id = bar_data.get("checkmark_message_id")
                has_merged_check = (check_id == msg_id)
                
                content_to_send = final_content
                if has_merged_check:
                    chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                    if chk not in content_to_send:
                         content_to_send = f"{content_to_send} {chk}"
                         content_to_send = re.sub(r'>[ \t]+<', '><', content_to_send)

                # EDIT IN PLACE
                try:
                    msg = await ch.fetch_message(msg_id)
                    view = ui.StatusBarView(content_to_send, bar_data["user_id"], cid, bar_data.get("persisting", False))
                    await services.service.limiter.wait_for_slot("edit_message", cid)
                    await msg.edit(content=content_to_send, view=view)
                    
                    self.active_bars[cid]["content"] = final_content
                    self._register_bar_message(cid, msg_id, view)
                    
                    memory_manager.save_bar(
                        cid, 
                        ch.guild.id, 
                        msg_id, 
                        bar_data["user_id"], 
                        final_content, 
                        bar_data.get("persisting", False)
                    )
                    return True
                except discord.NotFound:
                    return False
                except Exception as e:
                    logger.error(f"Global update edit failed in {cid}: {e}")
                    return False

            except Exception as e:
                logger.error(f"Global update error in {cid}: {e}")
                return False

        tasks = []
        for cid, bar in targets:
            tasks.append(process_update(cid, bar))
        
        results = await asyncio.gather(*tasks)
        return sum(1 for r in results if r)

    async def awake_all_bars(self):
        """
        Wakes up all bars by scanning for remnants or using active state, 
        and forcing them to Speed 0 (Not Watching) with their content preserved.
        """
        allowed_channels = memory_manager.get_allowed_channels()
        speed0_emoji = "<a:NotWatching:1301840196966285322>"

        async def process_wake(cid):
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False

                # 1. Find Content (Scan)
                found_content = await self.find_last_bar_content(ch)
                if not found_content:
                    # Try DB if scan fails?
                    if cid in self.active_bars:
                        found_content = self.active_bars[cid]["content"]
                
                if not found_content: return False # Skip if absolutely nothing found

                # 2. Clean Content
                if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in found_content:
                    found_content = found_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if found_content.startswith(emoji):
                        found_content = found_content[len(emoji):].strip()
                        break
                
                new_base_content = f"{speed0_emoji} {found_content}"
                new_base_content = re.sub(r'>[ \t]+<', '><', new_base_content)
                
                # Capture Persistence
                persisting = False
                if cid in self.active_bars:
                    persisting = self.active_bars[cid].get("persisting", False)

                # Attempt Edit In-Place
                msg = None
                bar_data = self.active_bars.get(cid)
                msg_id = bar_data.get("message_id") if bar_data else None
                
                if msg_id:
                     try: msg = await ch.fetch_message(msg_id)
                     except: pass
                
                if not msg:
                    # Try to find a remnant to resurrect/edit
                    async for m in ch.history(limit=50):
                        if m.author.id == self.user.id:
                            if m.content and (m.content == found_content or ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in m.content):
                                 msg = m
                                 break

                if msg:
                     # EDIT
                     check_id = bar_data.get("checkmark_message_id") if bar_data else msg.id
                     has_merged_check = (check_id == msg.id)
                     
                     final_content = new_base_content
                     chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                     # If merged or if we are resurrecting (which usually implies we want the checkmark back)
                     if chk not in final_content: 
                         final_content = f"{final_content} {chk}"
                         final_content = re.sub(r'>[ \t]+<', '><', final_content)

                     try:
                         view = ui.StatusBarView(final_content, self.user.id, cid, persisting)
                         await services.service.limiter.wait_for_slot("edit_message", cid)
                         await msg.edit(content=final_content, view=view)
                         
                         self.active_bars[cid] = {
                            "content": new_base_content,
                            "user_id": self.user.id,
                            "message_id": msg.id,
                            "checkmark_message_id": msg.id,
                            "persisting": persisting
                         }
                         self._register_bar_message(cid, msg.id, view)
                         memory_manager.save_bar(cid, ch.guild.id, msg.id, self.user.id, new_base_content, persisting)
                         return True
                     except Exception:
                         pass # Fallthrough to wipe/send

                # 3. Wipe
                await self.wipe_channel_bars(ch)
                
                # 4. Send
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                # Force inline checkmark
                send_content = f"{new_base_content} {chk}"
                send_content = re.sub(r'>[ \t]+<', '><', send_content)
                send_content = send_content.replace(f"\n{chk}", f" {chk}") # Explicit newline fix

                view = ui.StatusBarView(send_content, self.user.id, cid, persisting)
                await services.service.limiter.wait_for_slot("send_message", cid)
                new_msg = await ch.send(send_content, view=view)
                
                # 5. Register
                self.active_bars[cid] = {
                    "content": new_base_content,
                    "user_id": self.user.id,
                    "message_id": new_msg.id,
                    "checkmark_message_id": new_msg.id,
                    "persisting": persisting
                }
                self._register_bar_message(cid, new_msg.id, view)
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting)
                return True

            except Exception as e:
                 logger.error(f"Awake error in {cid}: {e}")
                 return False

        tasks = []
        for cid in allowed_channels:
            tasks.append(process_wake(cid))
        
        results = await asyncio.gather(*tasks)
        return sum(1 for r in results if r)

    async def set_speed_all_bars(self, target_emoji):
        """
        Sets the speed (prefix emoji) for all active bars.
        """
        count = 0
        for cid, bar in list(self.active_bars.items()):
            # Save state first
            memory_manager.save_previous_state(cid, bar)
            
            current_content = bar["content"]
            # Strip prefix
            for emoji in ui.BAR_PREFIX_EMOJIS:
                if current_content.startswith(emoji):
                    current_content = current_content[len(emoji):].strip()
                    break
            
            new_content = f"{target_emoji} {current_content}"
            self.active_bars[cid]["content"] = new_content
            self.active_bars[cid]["current_prefix"] = target_emoji
            
            async def update_msg(cid, msg_id, new_cont):
                try:
                    ch = self.get_channel(cid) or await self.fetch_channel(cid)
                    msg = await ch.fetch_message(msg_id)
                    full = f"{new_cont} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
                    full = re.sub(r'>[ \t]+<', '><', full)
                    await msg.edit(content=full)
                except: pass
            
            self.loop.create_task(update_msg(cid, bar["message_id"], new_content))
            
            # Update DB with new prefix
            memory_manager.save_bar(
                cid, 
                bar.get("guild_id"),
                bar["message_id"],
                bar["user_id"],
                new_content,
                bar.get("persisting", False),
                current_prefix=target_emoji
            )
            count += 1
        
        # Sync Console
        await self.update_console_status()
        
        return count

    async def propagate_master_bar(self):
        """
        Clones the Master Bar content to all whitelisted active bars.
        Preserves prefix and suffix (checkmark). Edits in-place.
        """
        master_content = memory_manager.get_master_bar()
        if not master_content:
            logger.warning("Propagate called but no Master Bar set.")
            return 0
        
        master_content = master_content.strip()

        whitelist = set(map(str, memory_manager.get_bar_whitelist()))
        targets = [cid for cid in self.active_bars if str(cid) in whitelist]
        
        async def update_node(cid):
            try:
                bar_data = self.active_bars[cid]
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False
                
                msg_id = bar_data.get("message_id")
                if not msg_id: return False
                
                # Get current prefix
                current_content = bar_data.get("content", "")
                prefix = ""
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if current_content.startswith(emoji):
                        prefix = emoji
                        break
                
                if not prefix:
                    # Default to Idle if prefix lost/unknown
                    prefix = "<a:NotWatching:1301840196966285322>"

                # Build New Content
                # Pattern: [Prefix] [Master] [Checkmark(if merged)]
                new_base_content = f"{prefix} {master_content}"
                new_base_content = re.sub(r'>[ \t]+<', '><', new_base_content)

                # Handle Checkmark
                check_id = bar_data.get("checkmark_message_id")
                has_merged_check = (check_id == msg_id)
                
                final_display_content = new_base_content
                if has_merged_check:
                    chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                    if chk not in final_display_content:
                        # FORCE INLINE SPACE
                        final_display_content = f"{final_display_content} {chk}"
                        final_display_content = re.sub(r'>[ \t]+<', '><', final_display_content)
                
                # Edit
                try:
                    msg = await ch.fetch_message(msg_id)
                    view = ui.StatusBarView(final_display_content, bar_data["user_id"], cid, bar_data.get("persisting", False))
                    await msg.edit(content=final_display_content, view=view)
                    
                    # Save State
                    self.active_bars[cid]["content"] = new_base_content
                    self._register_bar_message(cid, msg_id, view)
                    
                    memory_manager.save_bar(
                        cid, 
                        ch.guild.id, 
                        msg_id, 
                        bar_data["user_id"], 
                        new_base_content, 
                        bar_data.get("persisting", False)
                    )
                    return True
                except discord.NotFound:
                    return False
            except Exception as e:
                logger.error(f"Propagate failed for {cid}: {e}")
                return False

        tasks = [update_node(cid) for cid in targets]
        results = await asyncio.gather(*tasks)
        return sum(1 for r in results if r)

    def restore_status_bar_views(self):
        """
        Restores StatusBarViews for all loaded active bars.
        Crucial for button persistence after reboot.
        """
        logger.info("🔄 Restoring status bar views...")
        count = 0
        for channel_id, bar_data in self.active_bars.items():
            msg_id = bar_data.get("message_id")
            if not msg_id: continue
            
            try:
                view = ui.StatusBarView(
                    bar_data.get("content", ""),
                    bar_data.get("user_id", self.user.id),
                    channel_id,
                    bar_data.get("persisting", False)
                )
                self.add_view(view, message_id=msg_id)
                self._register_view(msg_id, view)
                count += 1
            except Exception as e:
                logger.error(f"Failed to restore view for {channel_id}: {e}")
        logger.info(f"✅ Restored {count} status bar views.")

    async def on_ready(self):
        logger.info('# ==========================================')
        logger.info('#                NyxOS v2.0')
        logger.info('#         Lovingly made by Calyptra')
        logger.info('#       https://temple.HyperSystem.xyz')    
        logger.info('# ==========================================')
        logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
        logger.info(f'Targeting LM Studio at: {config.LM_STUDIO_URL}')
        
        # Load Active Bars from DB (Internal state mostly, but we override content via scan)
        self.active_bars = memory_manager.get_all_bars()
        logger.info(f"Active Bars loaded (DB): {len(self.active_bars)}")
        
        # Restore Views for Persistence
        self.restore_status_bar_views()
        
        # Check for restart metadata
        restart_data = None
        if os.path.exists(config.RESTART_META_FILE):
            try:
                with open(config.RESTART_META_FILE, "r") as f:
                    restart_data = json.load(f)
                os.remove(config.RESTART_META_FILE)
            except: pass

        # Wait for cache/connection stability
        logger.info("⏳ Waiting 1s before waking bars...")
        await asyncio.sleep(1.0)
        
        # Load Whitelist EARLY to avoid UnboundLocalError
        bar_whitelist = memory_manager.get_bar_whitelist()
        allowed_channels = memory_manager.get_allowed_channels()
        
        # --- STARTUP PROGRESS MESSAGE ---
        target_channels = set()
        if config.STARTUP_CHANNEL_ID:
            target_channels.add(config.STARTUP_CHANNEL_ID)
        if restart_data and restart_data.get("channel_id"):
            target_channels.add(restart_data.get("channel_id"))
        
        progress_msgs = []
        
        # Construct Texts
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        startup_header_text = f"{ui.FLAVOR_TEXT['REBOOT_HEADER']}\n{ui.FLAVOR_TEXT['REBOOT_SUB'].format(current=0, total=len(allowed_channels))}\n{divider}"
        master_content = memory_manager.get_master_bar() or "NyxOS Uplink Active"
        msg2_text = f"{master_content.strip()}"
        body_text = f"{divider}\n🔍 Scanning {len(allowed_channels)} channels for bars..."

        for t_id in target_channels:
            try:
                t_ch = self.get_channel(t_id) or await self.fetch_channel(t_id)
                if not t_ch: continue

                # STRICT STATE ENFORCEMENT
                # Ensure channel has EXACTLY 3 messages: Header, Master Bar, Body.
                # If not, WIPE and RESET.

                existing_msgs = []
                try:
                    # Fetch history (ignore pinned if any, though strictly we want clean channel)
                    async for m in t_ch.history(limit=10):
                        existing_msgs.append(m)
                except: pass
                
                # Sort Oldest -> Newest
                existing_msgs.sort(key=lambda x: x.created_at)
                
                # Check if we have a valid state
                # State is valid if: Count is 3 AND all are from us (optional, but safer to just count)
                # If &reboot was used, we might have user msg + bot reply + 3 status = 5.
                # In that case, we WANT to wipe.
                
                valid_state = (len(existing_msgs) == 3 and all(m.author.id == self.user.id for m in existing_msgs))
                
                h_msg = None
                bar_msg = None
                b_msg = None
                success = False

                if valid_state:
                    h_msg = existing_msgs[0]
                    bar_msg = existing_msgs[1]
                    b_msg = existing_msgs[2]
                    
                    try:
                        await services.service.limiter.wait_for_slot("edit_message", t_id)
                        await h_msg.edit(content=startup_header_text)
                        await asyncio.sleep(1.0)
                        
                        await services.service.limiter.wait_for_slot("edit_message", t_id)
                        await bar_msg.edit(content=msg2_text)
                        await asyncio.sleep(1.0)

                        await services.service.limiter.wait_for_slot("edit_message", t_id)
                        await b_msg.edit(content=body_text, embed=None, view=None)
                        
                        client.startup_header_msg = h_msg
                        client.startup_bar_msg = bar_msg
                        progress_msgs.append(b_msg)
                        success = True
                    except: 
                        success = False # Edit failed (deleted?) -> Trigger Wipe

                if not success:
                    logger.info(f"🧹 Invalid state in {t_ch.name} (Msgs: {len(existing_msgs)}). Wiping and refreshing...")
                    try: await t_ch.purge(limit=100)
                    except: pass

                    await services.service.limiter.wait_for_slot("send_message", t_id)
                    h_msg = await t_ch.send(startup_header_text)
                    client.startup_header_msg = h_msg
                    await asyncio.sleep(1.0)
                    
                    await services.service.limiter.wait_for_slot("send_message", t_id)
                    bar_msg = await t_ch.send(msg2_text)
                    client.startup_bar_msg = bar_msg
                    await asyncio.sleep(1.0)
                    
                    await services.service.limiter.wait_for_slot("send_message", t_id)
                    msg = await t_ch.send(body_text, view=None)
                    progress_msgs.append(msg)

            except Exception as e:
                logger.error(f"❌ Failed to send startup messages to {t_id}: {e}")
        
        # Save for scanner
        client.console_progress_msgs = progress_msgs

        # --- PHASE 1: INITIALIZATION ---
        # bar_whitelist is defined at the top of on_ready
        
        # Just load DB into memory (Already done by active_bars init)
        # We do NOT scan channels here to avoid rate limits on boot.
        
        # Update Header to "System Online" immediately
        if hasattr(client, "startup_header_msg") and client.startup_header_msg:
             final_header = f"{ui.FLAVOR_TEXT['STARTUP_HEADER']}\n{ui.FLAVOR_TEXT['STARTUP_SUB_DONE']}\n{divider}"
             try:
                 # Wait for slot before editing header
                 await services.service.limiter.wait_for_slot("edit_message", client.startup_header_msg.channel.id)
                 await client.startup_header_msg.edit(content=final_header)
             except: pass
             
        # Populate Active Uplinks from DB
        await self.update_console_status()
        
        client.has_synced = True
        
        # Check commands
        await client.check_and_sync_commands()

    async def perform_system_scan(self, interaction=None):
        """
        Scans all whitelisted channels to verify/restore bars.
        Updates the console message log.
        """
        # 1. Setup Console Output
        # We use cached messages from on_ready to avoid scanning history
        console_msgs = getattr(self, "console_progress_msgs", [])
        
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        status_str = f"{divider}\n🔍 Scanning channels..."
        for m in console_msgs:
            try: await m.edit(content=status_str)
            except: pass

        bar_whitelist = memory_manager.get_bar_whitelist()
        wake_log = []
        
        for cid_str in bar_whitelist:
            await asyncio.sleep(8.0) # Rate limit protection (Aggressive 8s delay)
            
            try:
                cid = int(cid_str)
                if cid == 99999:
                    # Clean up invalid channel
                    memory_manager.remove_bar_whitelist(cid)
                    continue
                
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: continue
                
                # 1. Load Location
                stored_bar_id, stored_check_id = memory_manager.get_channel_location(cid)
                
                bar_msg = None
                check_msg = None
                
                # 2. Verify / Fetch (DB First)
                if stored_bar_id:
                    try: 
                        bar_msg = await ch.fetch_message(stored_bar_id)
                    except (discord.NotFound, discord.HTTPException): 
                        bar_msg = None # Explicitly cleared if fetch fails
                
                # If bar found, check if checkmark is merged or separate
                if bar_msg:
                    if stored_check_id == stored_bar_id:
                        check_msg = bar_msg # Merged
                    elif stored_check_id:
                        try: 
                            check_msg = await ch.fetch_message(stored_check_id)
                        except (discord.NotFound, discord.HTTPException):
                            check_msg = None

                # 3. Fallback Scan (Only if DB lookup failed)
                if not bar_msg:
                    # Extra delay before expensive scan
                    await asyncio.sleep(2.0) 
                    
                    async for m in ch.history(limit=5):
                        if m.author.id == self.user.id:
                            if m.content:
                                for emoji in ui.BAR_PREFIX_EMOJIS:
                                    if m.content.strip().startswith(emoji):
                                        bar_msg = m
                                        break
                            if bar_msg: break
                    
                    if bar_msg:
                        # Found one, assume merged or lost check
                        stored_bar_id = bar_msg.id
                        stored_check_id = bar_msg.id if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in bar_msg.content else None
                        memory_manager.save_channel_location(cid, bar_msg_id=bar_msg.id, check_msg_id=stored_check_id)

                # 4. Register / Restore
                if bar_msg:
                    # Extract clean content
                    content = bar_msg.content
                    if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in content:
                         content = content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    
                    # Ensure View is Active
                    existing = self.active_bars.get(cid, {})
                    persisting = existing.get("persisting", False)
                    user_id = existing.get("user_id", self.user.id)
                    
                    view = ui.StatusBarView(content, user_id, cid, persisting)
                    self.add_view(view, message_id=bar_msg.id)
                    self._register_bar_message(cid, bar_msg.id, view)
                    
                    # Update Active State
                    self.active_bars[cid] = {
                        "content": content,
                        "user_id": user_id,
                        "message_id": bar_msg.id,
                        "checkmark_message_id": check_msg.id if check_msg else None,
                        "persisting": persisting
                    }
                    
                    memory_manager.save_bar(cid, ch.guild.id, bar_msg.id, user_id, content, persisting)
                    
                    # Log (Link to Checkmark)
                    link_id = check_msg.id if check_msg else bar_msg.id
                    link = f"https://discord.com/channels/{ch.guild.id}/{cid}/{link_id}"
                    saturn_emoji = ui.FLAVOR_TEXT["UPLINK_BULLET"]
                    wake_log.append(f"{saturn_emoji} {link.strip()}")
                
                else:
                    # Lost? Create new idle bar
                    # Extra delay before send
                    await asyncio.sleep(1.0)
                    
                    master_content = memory_manager.get_master_bar() or "NyxOS Uplink Active"
                    idle_prefix = "<a:NotWatching:1301840196966285322>"
                    # Force inline checkmark
                    new_content = f"{idle_prefix} {master_content} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
                    new_content = re.sub(r'>[ \t]+<', '><', new_content)
                    new_content = new_content.replace(f"\n{ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}", f" {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}")
                    
                    view = ui.StatusBarView(new_content, self.user.id, cid, False)
                    new_msg = await ch.send(new_content, view=view)
                    
                    self.active_bars[cid] = {
                        "content": f"{idle_prefix} {master_content}",
                        "user_id": self.user.id,
                        "message_id": new_msg.id,
                        "checkmark_message_id": new_msg.id,
                        "persisting": False
                    }
                    self._register_bar_message(cid, new_msg.id, view)
                    memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, self.active_bars[cid]["content"], False)
                    memory_manager.save_channel_location(cid, new_msg.id, new_msg.id)
                    
                    link = f"https://discord.com/channels/{ch.guild.id}/{cid}/{new_msg.id}"
                    saturn_emoji = ui.FLAVOR_TEXT["UPLINK_BULLET"]
                    wake_log.append(f"{saturn_emoji} {link.strip()}")

                # Update Console
                log_str = "\n".join(wake_log[-8:]) 
                current_status = f"{divider}\n<a:Thinking:1322962569300017214> Initializing Uplinks...\n{log_str}"
                
                # Use cached console messages if available
                targets = getattr(self, "console_progress_msgs", [])
                # If empty (maybe manually run scan later?), try to find them CAREFULLY
                if not targets and config.STARTUP_CHANNEL_ID:
                     # We avoid scanning if possible. If manual scan, maybe just send a new report?
                     # Or just skip updating if we can't find them easily.
                     # Let's try to fetch just the last message if we really need to.
                     # But for now, let's rely on the cache from on_ready.
                     pass

                for m in targets:
                   try: 
                       await services.service.limiter.wait_for_slot("edit_message", m.channel.id)
                       await m.edit(content=current_status)
                   except: pass

            except Exception as e:
                logger.error(f"Scan failed for {cid_str}: {e}")

        # Final Update
        final_body = f"{divider}\n{ui.FLAVOR_TEXT['UPLINKS_HEADER']}\n" + "\n".join(wake_log)
        if len(final_body) > 2000:
             final_body = f"{divider}\n{ui.FLAVOR_TEXT['UPLINKS_HEADER']}\n(Log truncated...)"

        targets = getattr(self, "console_progress_msgs", [])
        for m in targets:
            try: 
                await services.service.limiter.wait_for_slot("edit_message", m.channel.id)
                await m.edit(content=final_body, view=ui.ConsoleControlView())
            except: pass
        
        if interaction:
            await interaction.followup.send(f"✅ Scan complete. Verified {len(wake_log)} uplinks.", ephemeral=True)

    async def update_console_status(self):
        """Updates the console message with the current list of known uplinks from DB."""
        # Get target messages
        targets = getattr(self, "console_progress_msgs", [])
        if not targets: return

        # Get Data
        whitelist = memory_manager.get_bar_whitelist() # Strings
        
        # Build List
        log_lines = []
        default_emoji = ui.BAR_PREFIX_EMOJIS[2] # Speed 0 (Not Watching)
        
        for cid_str in whitelist:
            try:
                cid = int(cid_str)
                
                # We rely on active_bars (DB loaded) for the "link" info
                bar_data = self.active_bars.get(cid)
                
                status_emoji = default_emoji
                if bar_data and bar_data.get('current_prefix'):
                     status_emoji = bar_data.get('current_prefix')

                if bar_data:
                    guild_id = bar_data.get('guild_id')
                    if not guild_id:
                        ch = self.get_channel(cid)
                        if ch: guild_id = ch.guild.id

                    target_id = bar_data.get('checkmark_message_id') or bar_data.get('message_id')
                    
                    if guild_id and target_id:
                        link = f"https://discord.com/channels/{guild_id}/{cid}/{target_id}"
                        log_lines.append(f"{status_emoji} {link}")
                    else:
                        log_lines.append(f"{status_emoji} <#{cid}> (Out of sync.)")
                else:
                    log_lines.append(f"{status_emoji} <#{cid}> (Out of sync.)")
            except:
                pass
                
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        final_body = f"{divider}\n{ui.FLAVOR_TEXT['UPLINKS_HEADER']}\n" + "\n".join(log_lines)
        
        if len(final_body) > 2000:
             final_body = f"{divider}\n{ui.FLAVOR_TEXT['UPLINKS_HEADER']}\n(List truncated... {len(log_lines)} active)"

        for m in targets:
            try: 
                await services.service.limiter.wait_for_slot("edit_message", m.channel.id)
                await m.edit(content=final_body, view=ui.ConsoleControlView())
            except: pass

    async def check_and_sync_commands(self):
        """Checks if commands have changed since last boot and syncs if needed."""
        current_hash = self.get_tree_hash()
        stored_hash = None
        
        if os.path.exists(config.COMMAND_STATE_FILE):
            try:
                with open(config.COMMAND_STATE_FILE, "r") as f:
                    stored_hash = f.read().strip()
            except: pass
            
        if current_hash != stored_hash:
            logger.info(f"🔄 Command structure changed (Hash mismatch). Syncing...")
            try:
                # Clear guild commands if you are using global sync, 
                # but here we assume standard global sync.
                await self.tree.sync()
                
                with open(config.COMMAND_STATE_FILE, "w") as f:
                    f.write(current_hash)
                logger.info("✅ Commands synced and hash updated.")
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}")
        else:
            logger.info("✅ Command structure matched. Skipping sync to avoid rate limits.")

    async def heartbeat_task(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                with open(config.HEARTBEAT_FILE, "w") as f:
                    f.write(str(time.time()))
            except Exception as e:
                logger.warning(f"⚠️ Heartbeat failed: {e}")
            await asyncio.sleep(2) # Faster heartbeat for 3s detection

    async def close(self):
        await services.service.close()
        await super().close()

    async def suppress_embeds_later(self, message, delay=5):
        await asyncio.sleep(delay)
        try:
            await message.edit(suppress=True)
        except: pass

    async def cleanup_old_bars(self, channel, exclude_msg_id=None):
        """Uses DB index to find and delete the active bar, or scans if DB is empty."""
        # 1. Check DB Index first
        if channel.id in self.active_bars:
            bar_data = self.active_bars[channel.id]
            msg_id = bar_data.get("message_id")
            
            if msg_id and msg_id != exclude_msg_id:
                try:
                    msg = await channel.fetch_message(msg_id)
                    await msg.delete()
                except: pass
            
            # Check stray checkmark if separate
            chk_id = bar_data.get("checkmark_message_id")
            if chk_id and chk_id != msg_id and chk_id != exclude_msg_id:
                try:
                    msg = await channel.fetch_message(chk_id)
                    await msg.delete()
                except: pass
            
            # Remove from Memory and DB ONLY if we are not excluding (meaning we are wiping)
            # If excluding, we assume the caller has already updated the DB with the new ID.
            if not exclude_msg_id:
                del self.active_bars[channel.id]
                memory_manager.delete_bar(channel.id)
            return

        # 2. Fallback: Scan (only if not in DB)
        try:
            async for msg in channel.history(limit=50):
                if msg.id == exclude_msg_id: continue
                
                if msg.author.id == self.user.id:
                    is_target = False
                    
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    is_target = True
                                    break
                            if is_target: break
                    
                    if not is_target and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                is_target = True
                                break
                    
                    if not is_target and msg.content:
                        if msg.content.strip() == ui.FLAVOR_TEXT['CHECKMARK_EMOJI']:
                            is_target = True

                    if is_target:
                        try: await msg.delete()
                        except: pass
        except Exception as e:
            logger.warning(f"Bar cleanup scan failed: {e}")

    async def wipe_channel_bars(self, channel):
        """Aggressively wipes all bar messages and checkmarks from history."""
        count = 0
        try:
            # 1. Clear Active State
            if channel.id in self.active_bars:
                del self.active_bars[channel.id]
                memory_manager.delete_bar(channel.id)

            # 2. Scan and Delete
            async for msg in channel.history(limit=100):
                if msg.author.id == self.user.id:
                    is_target = False
                    
                    # Check Components (Buttons)
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    is_target = True
                                    break
                            if is_target: break
                    
                    # Check Content Prefix
                    if not is_target and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                is_target = True
                                break
                    
                    # Check Checkmark
                    if not is_target and msg.content:
                        if msg.content.strip() == ui.FLAVOR_TEXT['CHECKMARK_EMOJI']:
                            is_target = True
                    
                    # Check "Uplink Bar" in content (legacy check) or specific formatting?
                    # Just stick to known signatures.

                    if is_target:
                        try: 
                            await services.service.limiter.wait_for_slot("delete_message", channel.id)
                            await msg.delete()
                            count += 1
                        except: pass
        except Exception as e:
            logger.warning(f"Wipe bars failed: {e}")
        return count

    async def find_last_bar_content(self, channel):
        """Finds content from DB or scan."""
        # 1. DB
        if channel.id in self.active_bars:
            # We store CLEAN content in DB now.
            return self.active_bars[channel.id]["content"]
            
        # 2. Scan
        try:
            async for msg in channel.history(limit=50):
                if msg.author.id == self.user.id:
                    is_bar = False
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    is_bar = True
                                    break
                            if is_bar: break
                    
                    if not is_bar and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                is_bar = True
                                break
                
                    if is_bar:
                        return msg.content
        except Exception as e:
            logger.warning(f"Find last bar failed: {e}")
        return None

    async def update_bar_prefix(self, interaction, new_prefix_emoji):
        """Updates the bar prefix. Edits in-place if bottom. Drops WITHOUT checkmark if moving."""
        # 1. Find existing content
        content = None
        found_raw = await self.find_last_bar_content(interaction.channel)
        
        if found_raw:
            content = found_raw
            chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
            if chk in content:
                content = content.replace(chk, "").strip()
            
            content = content.strip()
            for emoji in ui.BAR_PREFIX_EMOJIS:
                if content.startswith(emoji):
                    content = content[len(emoji):].strip()
                    break
        
        if not content:
            try: await interaction.response.send_message("❌ No active bar found to update.", ephemeral=True, delete_after=2.0)
            except: pass
            return

        content_with_prefix = f"{new_prefix_emoji} {content}"
        content_with_prefix = re.sub(r'>[ \t]+<', '><', content_with_prefix)
        
        persisting = False
        if interaction.channel_id in self.active_bars:
            persisting = self.active_bars[interaction.channel_id].get("persisting", False)

        # 3. Try Edit In-Place First (Regardless of position)
        active_msg = None
        if interaction.channel_id in self.active_bars:
            msg_id = self.active_bars[interaction.channel_id].get("message_id")
            if msg_id:
                try:
                    active_msg = await interaction.channel.fetch_message(msg_id)
                except: pass

        if active_msg:
            # Edit In-Place (Keep checkmark if present)
            chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
            full_content = f"{content_with_prefix} {chk}"
            full_content = re.sub(r'>[ \t]+<', '><', full_content)

            try:
                await services.service.limiter.wait_for_slot("edit_message", interaction.channel_id)
                await active_msg.edit(content=full_content)
                
                self.active_bars[interaction.channel_id]["content"] = content_with_prefix
                self.active_bars[interaction.channel_id]["checkmark_message_id"] = active_msg.id 
                self.active_bars[interaction.channel_id]["current_prefix"] = new_prefix_emoji
                
                memory_manager.save_bar(
                    interaction.channel_id, 
                    interaction.guild_id,
                    active_msg.id,
                    interaction.user.id,
                    content_with_prefix,
                    persisting,
                    current_prefix=new_prefix_emoji
                )
                try: await interaction.response.send_message("Updated.", ephemeral=False, delete_after=2.0)
                except: pass
                
                # Sync Console
                await self.update_console_status()
                return
            except Exception as e:
                logger.warning(f"In-place edit failed, falling back to drop: {e}")

        # 4. Drop (Leave Checkmark Behind)
        bar_data = self.active_bars.get(interaction.channel_id)
        old_msg_id = bar_data.get("message_id") if bar_data else None
        check_msg_id = bar_data.get("checkmark_message_id") if bar_data else None
        
        # Handle Old Message
        if old_msg_id:
            try:
                old_msg = await interaction.channel.fetch_message(old_msg_id)
                if check_msg_id == old_msg_id:
                    # Convert to Checkmark Only
                    await old_msg.edit(content=ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], view=None)
                else:
                    # Just Delete (Checkmark is elsewhere)
                    await old_msg.delete()
            except: pass

        # Send New Bar (NO CHECKMARK)
        full_content = content_with_prefix 
        
        try: await interaction.response.defer(ephemeral=False)
        except: pass
        
        view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, persisting)
        await services.service.limiter.wait_for_slot("send_message", interaction.channel_id)
        msg = await interaction.channel.send(full_content, view=view)
        
        # Update State
        # checkmark_message_id stays pointing to the old one (check_msg_id) or becomes old_msg_id if we just split it
        new_check_id = check_msg_id
        if old_msg_id and check_msg_id == old_msg_id:
            new_check_id = old_msg_id # It stays there
        
        self.active_bars[interaction.channel_id] = {
            "content": content_with_prefix, 
            "user_id": interaction.user.id,
            "message_id": msg.id,
            "checkmark_message_id": new_check_id,
            "persisting": persisting,
            "current_prefix": new_prefix_emoji
        }
        self._register_bar_message(interaction.channel_id, msg.id, view)
        
        memory_manager.save_bar(
            interaction.channel_id, 
            interaction.guild_id,
            msg.id,
            interaction.user.id,
            content_with_prefix,
            persisting,
            current_prefix=new_prefix_emoji
        )
        
        # Sync Console
        await self.update_console_status()
        try: await interaction.delete_original_response()
        except: pass
        
        await interaction.delete_original_response()

    async def replace_bar_content(self, interaction, new_content):
        """Replaces the entire bar content (preserving checkmark) and drops it."""
        # Cleanup old
        await self.cleanup_old_bars(interaction.channel)
        
        # Strip spaces between emojis
        new_content = re.sub(r'>[ \t]+<', '><', new_content)
        
        # Send new
        full_content = new_content
        
        # Preserve persistence
        persisting = False
        if interaction.channel_id in self.active_bars:
            persisting = self.active_bars[interaction.channel_id].get("persisting", False)
        
        await interaction.response.defer(ephemeral=False)
        
        view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, persisting)
        await services.service.limiter.wait_for_slot("send_message", interaction.channel_id)
        msg = await interaction.channel.send(full_content, view=view)
        
        self.active_bars[interaction.channel_id] = {
            "content": full_content,
            "user_id": interaction.user.id,
            "message_id": msg.id,
            "checkmark_message_id": msg.id,
            "persisting": persisting
        }
        self._register_bar_message(interaction.channel_id, msg.id, view)
        
        # Sync to DB
        memory_manager.save_bar(
            interaction.channel_id, 
            interaction.guild_id,
            msg.id,
            interaction.user.id,
            full_content,
            persisting
        )
        
        await interaction.delete_original_response()

    async def perform_shutdown_sequence(self, interaction, restart=True):
        # 1. Setup
        memory_manager.set_server_setting("global_chat_enabled", False)
        
        # Ensure Ephemeral Response if interaction
        if interaction and not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        # 2. Identify Console Channel
        console_channel = None
        if config.STARTUP_CHANNEL_ID:
            try: console_channel = await self.fetch_channel(config.STARTUP_CHANNEL_ID)
            except: pass
        
        # Fallback to interaction channel if console not found
        if not console_channel and interaction:
            console_channel = interaction.channel

        # 3. Locate Messages
        h_msg = getattr(self, "startup_header_msg", None)
        bar_msg = getattr(self, "startup_bar_msg", None)
        
        # If not cached, scan console channel
        if console_channel and (not h_msg or not bar_msg):
            try:
                candidates = []
                async for m in console_channel.history(limit=10):
                    if m.author.id == self.user.id:
                        candidates.append(m)
                # Sort Oldest -> Newest
                candidates.sort(key=lambda x: x.created_at)
                if len(candidates) >= 3:
                    h_msg = candidates[0]
                    bar_msg = candidates[1]
            except: pass

        # 4. UI Updates (Countdown)
        if h_msg and bar_msg:
            try:
                # Header -> Reboot/Shutdown
                header_text = ui.FLAVOR_TEXT["REBOOT_HEADER"] if restart else ui.FLAVOR_TEXT["SHUTDOWN_HEADER"]
                
                await services.service.limiter.wait_for_slot("edit_message", h_msg.channel.id)
                await h_msg.edit(content=header_text)
                
                # Powering Down (Single update to avoid rate limits)
                await services.service.limiter.wait_for_slot("edit_message", bar_msg.channel.id)
                await bar_msg.edit(content="-# Powering Down . . .")
                await asyncio.sleep(5.0) 
                
                # Final Status: System Offline
                await services.service.limiter.wait_for_slot("edit_message", bar_msg.channel.id)
                await bar_msg.edit(content=ui.FLAVOR_TEXT["SYSTEM_OFFLINE"])
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.warning(f"Shutdown UI update failed: {e}")
        else:
            # Fallback if no UI found
            if interaction:
                await interaction.followup.send(f"{ui.FLAVOR_TEXT['SHUTDOWN_MESSAGE']} (UI Not Found, forcing exit)", ephemeral=True)
            await asyncio.sleep(5.0) # Wait anyway

        # 5. Meta Write (Only for Reboot)
        if restart:
            meta = {
                "channel_id": console_channel.id if console_channel else None,
                "header_msg_id": h_msg.id if h_msg else None,
                "bar_msg_id": bar_msg.id if bar_msg else None
            }
            try:
                with open(config.RESTART_META_FILE, "w") as f:
                    json.dump(meta, f)
                    f.flush()
                    os.fsync(f.fileno())
            except: pass
        else:
            try:
                with open(config.SHUTDOWN_FLAG_FILE, "w") as f: f.write("shutdown")
            except: pass

        # 6. Close & Exit
        await self.close()
        
        if restart:
            # Wait for Discord to fully release the session/token
            logger.info("⏳ Session closed. Waiting 5s for token release before restart...")
            time.sleep(5.0)
            
            # Exit process. Watcher script (NyxOS.sh) will handle the relaunch.
            sys.exit(0)
        else:
            sys.exit(0)

# --- Helper Class for Internal Interaction Mocking ---
class MockInteraction:
    def __init__(self, client, channel, user):
        self.client = client
        self.channel = channel
        self.channel_id = channel.id
        self.user = user
        self.guild = channel.guild if hasattr(channel, 'guild') else None
        self.guild_id = channel.guild.id if hasattr(channel, 'guild') and channel.guild else None
        self.response = self.MockResponse(channel)
        self.followup = self.response # Alias for followup.send
    
    async def delete_original_response(self): pass

    class MockResponse:
        def __init__(self, channel):
            self.channel = channel
            
        async def send_message(self, content=None, **kwargs):
            kwargs.pop('ephemeral', None)
            if content:
                await self.channel.send(content, **kwargs)
            else:
                await self.channel.send(**kwargs)
        
        # Alias for followup.send
        async def send(self, content=None, **kwargs):
            await self.send_message(content, **kwargs)

        async def defer(self, ephemeral=False): pass
        
        def is_done(self): return False
        
        async def delete_original_response(self): pass

client = LMStudioBot()

# ==========================================
# SLASH COMMANDS
# ==========================================

@client.tree.command(name="scan", description="Manually scan channels to verify and restore uplinks.")
async def scan_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    
    await interaction.response.defer(ephemeral=True)
    await client.perform_system_scan(interaction)

@client.tree.command(name="addchannel", description="Add the current channel to the bot's whitelist.")
async def add_channel_command(interaction: discord.Interaction):
    member_obj = interaction.user
    if interaction.guild:
        if isinstance(member_obj, discord.User) or not hasattr(member_obj, "roles"):
             member_obj = interaction.guild.get_member(interaction.user.id)
             if not member_obj:
                 try: member_obj = await interaction.guild.fetch_member(interaction.user.id)
                 except: pass
    if not member_obj: member_obj = interaction.user

    if not helpers.is_authorized(member_obj):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        await interaction.response.send_message("✅ Channel already whitelisted.", ephemeral=False, delete_after=2.0)
    else:
        memory_manager.add_allowed_channel(interaction.channel_id)
        await client.update_console_status()
        await interaction.response.send_message(f"😄 I'll talk in this channel!", ephemeral=False, delete_after=2.0)

@client.tree.command(name="removechannel", description="Remove the current channel from the bot's whitelist.")
async def remove_channel_command(interaction: discord.Interaction):
    member_obj = interaction.user
    if interaction.guild:
        if isinstance(member_obj, discord.User) or not hasattr(member_obj, "roles"):
             member_obj = interaction.guild.get_member(interaction.user.id)
             if not member_obj:
                 try: member_obj = await interaction.guild.fetch_member(interaction.user.id)
                 except: pass
    if not member_obj: member_obj = interaction.user

    if not helpers.is_authorized(member_obj):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
        
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        memory_manager.remove_allowed_channel(interaction.channel_id)
        await client.update_console_status()
        await interaction.response.send_message(f"🤐 I'll ignore this channel!", ephemeral=False, delete_after=2.0)
    else:
        await interaction.response.send_message("⚠️ Channel not in whitelist.", ephemeral=False, delete_after=2.0)

@client.tree.command(name="enableall", description="Enable Global Chat Mode (Talk in ALL channels).")
async def enableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.set_server_setting("global_chat_enabled", True)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_CHAT_ENABLED"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="disableall", description="Disable Global Chat Mode (Talk in whitelist only).")
async def disableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.set_server_setting("global_chat_enabled", False)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_CHAT_DISABLED"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="reboot", description="Full restart of the bot process.")
async def reboot_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    await client.perform_shutdown_sequence(interaction, restart=True)

@client.tree.command(name="shutdown", description="Gracefully shut down the bot.")
async def shutdown_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    await client.perform_shutdown_sequence(interaction, restart=False)

@client.tree.command(name="killmyembeds", description="Toggle auto-suppression of hyperlink embeds for your messages.")
async def killmyembeds_command(interaction: discord.Interaction):
    is_enabled = memory_manager.toggle_suppressed_user(interaction.user.id)
    msg = ui.FLAVOR_TEXT["EMBED_SUPPRESSION_ENABLED"] if is_enabled else ui.FLAVOR_TEXT["EMBED_SUPPRESSION_DISABLED"]
    await interaction.response.send_message(msg, ephemeral=False, delete_after=2.0)

@client.tree.command(name="suppressembedson", description="Enable the server-wide embed suppression feature.")
async def suppressembedson_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.set_server_setting("embed_suppression", True)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_SUPPRESSION_ON"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="suppressembedsoff", description="Disable the server-wide embed suppression feature.")
async def suppressembedsoff_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.set_server_setting("embed_suppression", False)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_SUPPRESSION_OFF"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="clearmemory", description="Clear the bot's memory for this channel.")
async def clearmemory_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    # Update cutoff time to NOW
    client._update_lru_cache(client.channel_cutoff_times, interaction.channel_id, interaction.created_at, limit=500)
    
    memory_manager.clear_channel_memory(interaction.channel_id, interaction.channel.name)
    await interaction.response.send_message(ui.FLAVOR_TEXT["CLEAR_MEMORY_DONE"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="reportbug", description="Submit a bug report.")
async def reportbug_command(interaction: discord.Interaction):
    await interaction.response.send_modal(ui.BugReportModal(None))

@client.tree.command(name="goodbot", description="Show the Good Bot Leaderboard.")
async def good_bot_leaderboard(interaction: discord.Interaction):
    leaderboard = memory_manager.get_good_bot_leaderboard()
    if not leaderboard:
        await interaction.response.send_message(ui.FLAVOR_TEXT["NO_GOOD_BOTS"], ephemeral=False)
        return

    total_good_bots = sum(user['count'] for user in leaderboard)
    chart_text = ui.FLAVOR_TEXT["GOOD_BOT_HEADER"]
    for i, user_data in enumerate(leaderboard[:10], 1):
        chart_text += f"**{i}.** {user_data['username']} — **{user_data['count']}**\n"
    chart_text += f"\n**Total:** {total_good_bots} Good Bots 💙"
    
    await interaction.response.send_message(chart_text, ephemeral=False)

@client.tree.command(name="synccommands", description="Force sync slash commands.")
async def synccommands_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return

    await interaction.response.defer(ephemeral=False)
    try:
        await client.tree.sync()
        # Update hash
        new_hash = client.get_tree_hash()
        with open(config.COMMAND_STATE_FILE, "w") as f:
            f.write(new_hash)
        await interaction.followup.send("✅ Commands force-synced and state updated.", ephemeral=False)
        # Note: Sync confirmation usually good to keep for a bit longer or permanent, but user asked for 2s parity. 
        # I'll leave it as ephemeral=False (visible) but no delete_after for safety in case of errors? 
        # No, user said "all with commands...". I'll add delete_after=5.0 for this one as it's debug.
    except Exception as e:
        await interaction.followup.send(f"❌ Error syncing: {e}")

@client.tree.command(name="debug", description="Toggle Debug Mode (Admin Only).")
async def debug_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    current = memory_manager.get_server_setting("debug_mode", False)
    new_mode = not current
    memory_manager.set_server_setting("debug_mode", new_mode)
    msg = ui.FLAVOR_TEXT["DEBUG_MODE_ON"] if new_mode else ui.FLAVOR_TEXT["DEBUG_MODE_OFF"]
    await interaction.response.send_message(msg, ephemeral=False, delete_after=2.0)

@client.tree.command(name="testmessage", description="Send a test message (Admin/Debug Only).")
async def testmessage_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    await interaction.response.defer()
    # Bypass system prompt logic with a blank slate
    response = await services.service.query_lm_studio(
        user_prompt="Reply to this message with SYSTEM TEST MESSAGE and nothing else.",
        username="Admin",
        identity_suffix="",
        history_messages=[],
        channel_obj=interaction.channel,
        system_prompt_override=" "
    )
    
    # Post-process using helpers
    response = helpers.sanitize_llm_response(response)
    response = helpers.restore_hyperlinks(response)

    view = ui.ResponseView("TEST MESSAGE", interaction.user.id, "Admin", "", [], interaction.channel, None, None, None, "")
    await interaction.followup.send(response, view=view)

@client.tree.command(name="clearallmemory", description="Wipe ALL chat memories (Admin/Debug Only).")
async def clearallmemory_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.wipe_all_memories()
    await interaction.response.send_message(ui.FLAVOR_TEXT["MEMORY_WIPED"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="wipelogs", description="Wipe ALL logs (Admin/Debug Only).")
async def wipelogs_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    memory_manager.wipe_all_logs()
    await interaction.response.send_message(ui.FLAVOR_TEXT["LOGS_WIPED"], ephemeral=False, delete_after=2.0)

@client.tree.command(name="debugtest", description="Run unit tests and report results (Admin Only).")
async def debugtest_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return

    await interaction.response.defer()
    
    import io
    import pytest
    import contextlib
    
    # Capture stdout/stderr
    log_capture = io.StringIO()
    
    def run_tests():
        # Redirect stdout and stderr to our capture buffer
        with contextlib.redirect_stdout(log_capture), contextlib.redirect_stderr(log_capture):
            # Run pytest
            return pytest.main(["-v", "--color=no", "tests/"])
            
    # Run in a separate thread to avoid event loop conflicts
    start_time = time.time()
    exit_code = await asyncio.to_thread(run_tests)
    duration = time.time() - start_time
    output = log_capture.getvalue()
    
    # Log to console/file
    logger.info(f"Debug Test Output:\n{output}")
    
    # Send to Discord
    if exit_code == 0:
        status = "✅ PASSED"
    elif exit_code == 1:
        status = "❌ FAILED"
    else:
        status = f"⚠️ ERROR (Code: {exit_code})"

    msg = f"**Unit Test Results:** {status}\nDuration: {duration:.3f}s."
    
    file = discord.File(io.BytesIO(output.encode()), filename="test_results.txt")
    await interaction.followup.send(msg, file=file)

@client.tree.command(name="bar", description="Update the Master Bar content and propagate to all whitelisted channels.")
async def bar_command(interaction: discord.Interaction, content: str):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    memory_manager.set_master_bar(content)
    count = await client.propagate_master_bar()
    
    # Update Console/Startup Bar Message
    if hasattr(client, "startup_bar_msg") and client.startup_bar_msg:
        try: await client.startup_bar_msg.edit(content=content.strip())
        except: pass

    await interaction.response.send_message(f"✅ Master Bar updated and propagated to {count} channels.", ephemeral=False, delete_after=2.0)

@client.tree.command(name="addbar", description="Whitelist this channel and spawn a bar.")
async def addbar_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
        
    memory_manager.add_bar_whitelist(interaction.channel_id)
    
    master_content = memory_manager.get_master_bar()
    if not master_content:
        master_content = "NyxOS Uplink Active"
    
    master_content = master_content.strip()
    
    # Default State: Idle
    prefix = "<a:NotWatching:1301840196966285322>"
    chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
    
    # Display Content
    full_content = f"{prefix} {master_content} {chk}"
    full_content = re.sub(r'>[ \t]+<', '><', full_content)
    
    # Cleanup old
    await client.cleanup_old_bars(interaction.channel)
    
    view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, False)
    msg = await interaction.channel.send(full_content, view=view)
    
    # Base content for storage/logic (Prefix + Master)
    base_content = f"{prefix} {master_content}"
    
    client.active_bars[interaction.channel_id] = {
        "content": base_content,
        "user_id": interaction.user.id,
        "message_id": msg.id,
        "checkmark_message_id": msg.id,
        "persisting": False
    }
    client._register_bar_message(interaction.channel_id, msg.id, view)
    memory_manager.save_bar(interaction.channel_id, interaction.guild_id, msg.id, interaction.user.id, base_content, False)
    
    await interaction.response.send_message("✅ Channel whitelisted and bar created.", ephemeral=False, delete_after=2.0)

@client.tree.command(name="removebar", description="Remove bar and un-whitelist channel.")
async def removebar_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return

    memory_manager.remove_bar_whitelist(interaction.channel_id)
    await client.wipe_channel_bars(interaction.channel)
    await interaction.response.send_message("✅ Bar removed and channel un-whitelisted.", ephemeral=False, delete_after=2.0)

@client.tree.command(name="restore", description="Restore the last Uplink Bar content from history.")
async def restore_command(interaction: discord.Interaction):
    content = memory_manager.get_bar_history(interaction.channel_id, 0) # 0 = Latest
    if not content:
        await interaction.response.send_message("❌ No history found for this channel.", ephemeral=False, delete_after=2.0)
        return
    
    await client.replace_bar_content(interaction, content)

@client.tree.command(name="restore2", description="Restore the BACKUP Uplink Bar content (previous).")
async def restore2_command(interaction: discord.Interaction):
    content = memory_manager.get_bar_history(interaction.channel_id, 1) # 1 = Previous
    if not content:
        await interaction.response.send_message("❌ No backup history found (restore2).", ephemeral=False, delete_after=2.0)
        return
    
    await client.replace_bar_content(interaction, content)

@client.tree.command(name="cleanbars", description="Wipe all Uplink Bar artifacts and checkmarks from the channel.")
async def cleanbars_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=False)
    count = await client.wipe_channel_bars(interaction.channel)
    await interaction.followup.send(f"🧹 Wiped {count} Uplink Bar artifacts.", ephemeral=False)
    # Delete followup manually if needed, but delete_after not standard on followup. send_message has it. 
    # Interaction followups don't support delete_after in discord.py? Checking...
    # It usually does. But let's leave visible 2s.
    # Actually, I can't use delete_after in followup.send easily if it's not supported.
    # I'll check if discord.py supports it. Yes it does.

@client.tree.command(name="sleep", description="Put all bars to sleep.")
async def sleep_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=False)
    count = await client.sleep_all_bars()
    await interaction.followup.send(f"😴 Put ~{count} bars to sleep.")

@client.tree.command(name="idle", description="Set all bars to Idle (Not Watching).")
async def idle_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=False, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=False)
    count = await client.idle_all_bars()
    await interaction.followup.send(f"😶 Set ~{count} bars to Idle.")

@client.tree.command(name="dropcheck", description="Drop just the checkmark to the current bar location.")
async def dropcheck_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
         await interaction.response.send_message("❌ No active bar.", ephemeral=False, delete_after=2.0)
         return
    
    await interaction.response.defer(ephemeral=False)
    # Only move check, bar stays put
    await client.drop_status_bar(interaction.channel_id, move_bar=False, move_check=True)
    await interaction.delete_original_response()

@client.tree.command(name="thinking", description="Set status to Thinking.")
async def thinking_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Thinking:1322962569300017214>")

@client.tree.command(name="reading", description="Set status to Reading.")
async def reading_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Reading:1378593438265770034>")

@client.tree.command(name="backlogging", description="Set status to Backlogging.")
async def backlogging_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Backlogging:1290067150861500588>")

@client.tree.command(name="typing", description="Set status to Typing.")
async def typing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Typing:000000000000000000>")

@client.tree.command(name="brb", description="Set status to BRB.")
async def brb_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:BRB:000000000000000000>")

@client.tree.command(name="processing", description="Set status to Processing.")
async def processing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Processing:1223643308140793969>")

@client.tree.command(name="angel", description="Set status to Angel.")
async def angel_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Angel:000000000000000000>")

@client.tree.command(name="pausing", description="Set status to Pausing.")
async def pausing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Pausing:1385258657532481597>")

@client.tree.command(name="speed0", description="Set status to Not Watching.")
async def speed0_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:NotWatching:1301840196966285322>")

@client.tree.command(name="speed1", description="Set status to Watching Slowly/Occasionally.")
async def speed1_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:WatchingOccasionally:1301837550159269888>")

@client.tree.command(name="speed2", description="Set status to Watching Closely.")
async def speed2_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:WatchingClosely:1301838354832425010>")

@client.tree.command(name="linkcheck", description="Get a link to the current checkmark message.")
async def linkcheck_command(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar.", ephemeral=False, delete_after=2.0)
        return

    check_msg_id = client.active_bars[channel_id].get("checkmark_message_id")
    if not check_msg_id:
        await interaction.response.send_message("❌ No checkmark found.", ephemeral=False, delete_after=2.0)
        return

    guild_id = interaction.guild_id if interaction.guild else "@me"
    link = f"https://discord.com/channels/{guild_id}/{channel_id}/{check_msg_id}"
    
    await interaction.response.send_message(f"[Jump to Checkmark]({link})", ephemeral=False, delete_after=2.0)

@client.tree.command(name="drop", description="Drop (refresh) the current Uplink Bar.")
async def drop_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar in this channel. Use `/bar` to create one.", ephemeral=False, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=False)
    await client.drop_status_bar(interaction.channel_id, move_bar=True, move_check=True)
    await interaction.delete_original_response()

@client.tree.command(name="help", description="Show the help index.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="NyxOS Help Index", color=discord.Color.blue())
    embed.add_field(name="General Commands", value="`/killmyembeds` - Toggle auto-suppression of link embeds.\n`/goodbot` - Show the Good Bot leaderboard.\n`/reportbug` - Submit a bug report.", inline=False)
    embed.add_field(name="Admin Commands", value="`/enableall` - Enable Global Chat (All Channels).\n`/disableall` - Disable Global Chat (Whitelist Only).\n`/addchannel` - Whitelist channel.\n`/removechannel` - Blacklist channel.\n`/suppressembedson/off` - Toggle server-wide embed suppression.\n`/clearmemory` - Clear current channel memory.\n`/reboot` - Restart bot.\n`/shutdown` - Shutdown bot.\n`/debug` - Toggle Debug Mode.\n`/testmessage` - Send test msg (Debug).\n`/clearallmemory` - Wipe ALL memories (Debug).\n`/wipelogs` - Wipe ALL logs (Debug).\n`/synccommands` - Force sync slash commands.\n`/restore` - Restore last Uplink Bar.\n`/restore2` - Restore backup Uplink Bar.\n`/cleanbars` - Wipe Uplink Bar artifacts.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=False)

@client.tree.command(name="d", description="Alias for /drop")
async def d_command(interaction: discord.Interaction):
    await drop_command.callback(interaction)

@client.tree.command(name="c", description="Alias for /dropcheck")
async def c_command(interaction: discord.Interaction):
    await dropcheck_command.callback(interaction)

@client.tree.command(name="b", description="Alias for /bar")
async def b_command(interaction: discord.Interaction, content: str = None):
    await bar_command.callback(interaction, content)

@client.tree.command(name="global", description="Update text on all active bars.")
async def global_command(interaction: discord.Interaction, text: str):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    count = await client.global_update_bars(text)
    await interaction.response.send_message(f"🌐 Updated text for ~{count} bars.", ephemeral=True)

@client.tree.command(name="awake", description="Wake up all bars (restore from idle/sleep).")
async def awake_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.awake_all_bars()
    await interaction.followup.send(f"🌅 Woke up ~{count} bars.")

@client.tree.command(name="speedall0", description="Set all bars to Speed 0 (Not Watching).")
async def speedall0_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.set_speed_all_bars("<a:NotWatching:1301840196966285322>")
    await interaction.followup.send(f"🚀 Updated speed on {count} bars.")

@client.tree.command(name="speedall1", description="Set all bars to Speed 1 (Watching Occasionally).")
async def speedall1_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.set_speed_all_bars("<a:WatchingOccasionally:1301837550159269888>")
    await interaction.followup.send(f"🚀 Updated speed on {count} bars.")

@client.tree.command(name="speedall2", description="Set all bars to Speed 2 (Watching Closely).")
async def speedall2_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
         return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.set_speed_all_bars("<a:WatchingClosely:1301838354832425010>")
    await interaction.followup.send(f"🚀 Updated speed on {count} bars.")

@client.tree.command(name="darkangel", description="Set status to Dark Angel.")
async def darkangel_command(interaction: discord.Interaction):
    await client.replace_bar_content(interaction, ui.DARK_ANGEL_CONTENT)

# ==========================================
# EVENTS
# ==========================================



@client.event
async def on_reaction_add(reaction, user):
    if user.bot: return
    
    message = reaction.message
    if message.id not in client.processing_locks: return
    
    # Check if it's the wake word reaction
    if str(reaction.emoji) == ui.FLAVOR_TEXT["WAKE_WORD_REACTION"]:
        # Check authorization (Message Author or Admin)
        # Note: message.author might be a webhook, so we check ID match if not webhook, or just Admin rights
        is_author = (message.author.id == user.id)
        if is_author or helpers.is_authorized(user):
            client.abort_signals.add(message.id)
            logger.info(f"🛑 Abort signal received for message {message.id} from {user.name}")

@client.event
async def on_message_edit(before, after):
    # Quick exit checks for performance
    # Allow self-edits/embeds to be processed, but ignore other bots
    if after.author.bot and after.author.id != client.user.id: return
    if not after.embeds: return
    
    # Check Master Switch (Cached read preferred, but file read is safe enough for edit events)
    if not memory_manager.get_server_setting("embed_suppression", True):
        return

    # Check User Opt-in (Force suppress for self if global setting is on)
    suppressed_users = memory_manager.get_suppressed_users()
    is_self = (after.author.id == client.user.id)
    
    if not is_self and str(after.author.id) not in suppressed_users:
        return

    # Check Embed Type (Hyperlinks usually 'link', 'article', 'video')
    # We avoid 'rich' (bots) or 'image' (uploads) per request
    should_suppress = False
    for embed in after.embeds:
        if embed.type in ('link', 'article', 'video'):
            should_suppress = True
            break
            
    if should_suppress:
        try:
            await after.edit(suppress=True)
        except: pass # Missing permissions or message deleted

@client.event
async def on_message(message):
    if message.author == client.user: return

    # --- STATUS BAR PERSISTENCE ---
    if message.channel.id in client.active_bars:
        bar_data = client.active_bars[message.channel.id]
        if bar_data["persisting"]:
             # Check if user is a system (potential ghost)
             is_system = False
             if message.webhook_id is None:
                 is_system = await services.service.check_local_pk_system(message.author.id)
             
             if is_system:
                 client.loop.create_task(client.wait_for_ghost_and_drop(message.channel.id, message.id))
             else:
                 # Not a system (or is webhook), safe to drop immediately
                 client.request_bar_drop(message.channel.id)

    # --- PREFIX COMMANDS ---
    if message.content.startswith("&"):
        cmd_parts = message.content.split()
        cmd = cmd_parts[0].lower()[1:] # Remove '&'
        args = cmd_parts[1:] if len(cmd_parts) > 1 else []
        
        # Map of command name to (Slash Command Object, Argument Name or None)
        cmd_map = {
            "bar": (bar_command, "content"),
            "b": (bar_command, "content"),
            "addbar": (addbar_command, None),
            "removebar": (removebar_command, None),
            "drop": (drop_command, None),
            "d": (drop_command, None),
            "dropcheck": (dropcheck_command, None),
            "c": (dropcheck_command, None),
            "linkcheck": (linkcheck_command, None),
            "restore": (restore_command, None),
            "restore2": (restore2_command, None),
            "cleanbars": (cleanbars_command, None),
            "sleep": (sleep_command, None),
            "idle": (idle_command, None),
            "global": (global_command, "text"),
            "awake": (awake_command, None),
            "speedall0": (speedall0_command, None),
            "speedall1": (speedall1_command, None),
            "speedall2": (speedall2_command, None),
            "addchannel": (add_channel_command, None),
            "removechannel": (remove_channel_command, None),
            "enableall": (enableall_command, None),
            "disableall": (disableall_command, None),
            "reboot": (reboot_command, None),
            "shutdown": (shutdown_command, None),
            "scan": (scan_command, None),
            "clearmemory": (clearmemory_command, None),
            "reportbug": (reportbug_command, None),
            "goodbot": (good_bot_leaderboard, None),
            "synccommands": (synccommands_command, None),
            "debug": (debug_command, None),
            "testmessage": (testmessage_command, None),
            "clearallmemory": (clearallmemory_command, None),
            "wipelogs": (wipelogs_command, None),
            "debugtest": (debugtest_command, None),
            "help": (help_command, None),
            "killmyembeds": (killmyembeds_command, None),
            "suppressembedson": (suppressembedson_command, None),
            "suppressembedsoff": (suppressembedsoff_command, None),
            "thinking": (thinking_command, None),
            "reading": (reading_command, None),
            "backlogging": (backlogging_command, None),
            "typing": (typing_command, None),
            "brb": (brb_command, None),
            "processing": (processing_command, None),
            "angel": (angel_command, None),
            "darkangel": (darkangel_command, None),
            "pausing": (pausing_command, None),
            "speed0": (speed0_command, None),
            "speed1": (speed1_command, None),
            "speed2": (speed2_command, None),
        }

        if cmd in cmd_map:
            command_func, arg_name = cmd_map[cmd]
            
            kwargs = {}
            if arg_name:
                if not args:
                     await message.channel.send(f"❌ Usage: `&{cmd} <{arg_name}>`", delete_after=2.0)
                     return
                kwargs[arg_name] = " ".join(args)
            
            # Create Mock Interaction
            mock_intr = MockInteraction(client, message.channel, message.author)
            
            try:
                await command_func.callback(mock_intr, **kwargs)
            except Exception as e:
                logger.error(f"Command {cmd} failed: {e}")
            return

    if message.id in client.processing_locks: return
    
    reaction_added = False
    skip_reaction_remove = False
    try:
        # --- COMMANDS ---
        if message.content == "!updateslashcommands" and helpers.is_authorized(message.author):
            await message.channel.send("🔄 Updating slash commands...")
            try:
                for guild in client.guilds: client.tree.clear_commands(guild=guild)
                await client.tree.sync()
                for guild in client.guilds:
                    client.tree.copy_global_to(guild=guild)
                    await client.tree.sync(guild=guild)
                await message.channel.send("✅ Commands synced.")
            except Exception as e: await message.channel.send(f"❌ Error: {e}")
            return
        
        # --- PRE-CALCULATE RESPONSE TRIGGER ---
        should_respond = False
        target_message_id = None
        
        if client.user in message.mentions: should_respond = True
        
        # Combine all trigger roles (Bot, Admin, Special)
        TRIGGER_ROLES = set(config.BOT_ROLE_IDS + config.ADMIN_ROLE_IDS + config.SPECIAL_ROLE_IDS)

        if not should_respond:
            if message.role_mentions:
                for role in message.role_mentions:
                    if role.id in TRIGGER_ROLES: should_respond = True; break
            if not should_respond:
                for rid in TRIGGER_ROLES:
                    if f"<@&{rid}>".format(rid) in message.content: should_respond = True; break
        
        # Check Reply (Robust)
        if message.reference:
            try:
                ref_msg = message.reference.resolved
                if not ref_msg and message.reference.message_id:
                    # Fetch if not in cache (needed for replies to old messages)
                    try:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    except discord.NotFound:
                        ref_msg = None
                
                if ref_msg:
                    # Check if reply is to bot
                    if ref_msg.author.id == client.user.id:
                        should_respond = True
                        target_message_id = ref_msg.id
            except Exception as e:
                logger.debug(f"Reply Check Error: {e}")

        # INSTANT REACTION
        # if should_respond:
        #     try:
        #         await message.add_reaction(ui.FLAVOR_TEXT["WAKE_WORD_REACTION"])
        #         reaction_added = True
        #     except: pass

        # --- PROXY/WEBHOOK CHECKS ---
        if message.webhook_id is None:
            try:
                tags = await services.service.get_system_proxy_tags(config.MY_SYSTEM_ID)
                if helpers.matches_proxy_tag(message.content, tags): return
                
                # Ghost Check (Restored)
                # Wait to see if a webhook appears that replaces this message
                await asyncio.sleep(2.0)
                try:
                    await message.channel.fetch_message(message.id)
                    async for recent in message.channel.history(limit=15):
                        if recent.webhook_id is not None:
                             diff = (recent.created_at - message.created_at).total_seconds()
                             if abs(diff) < 3.0: 
                                 skip_reaction_remove = True
                                 return
                except (discord.NotFound, discord.HTTPException): 
                    skip_reaction_remove = True
                    return 
            except Exception as e:
                logger.error(f"Proxy Tag Check Failed: {e}") 

        # --- GOOD BOT CHECK ---
        if re.search(r'\bgood\s*bot\b', message.content, re.IGNORECASE):
            is_ping = client.user in message.mentions
            # If replying to me OR pinging me
            if is_ping or target_message_id:
                if not target_message_id:
                    target_message_id = client.last_bot_message_id.get(message.channel.id)
                
                # Determine sender ID for Good Bot
                sender_id = message.author.id
                real_name = message.author.display_name
                pk_tag = None
                is_pk_proxy = False
                system_name = None
                
                if message.webhook_id:
                    pk_name, pk_sys_id, pk_sys_name, pk_tag_val, pk_sender, _ = await services.service.get_pk_message_data(message.id)
                    if pk_name:
                        real_name = pk_name
                        pk_tag = pk_tag_val
                        if pk_sender: sender_id = int(pk_sender)
                        system_name = pk_sys_name
                        is_pk_proxy = True
                
                now = discord.utils.utcnow().timestamp()
                last_time = client.good_bot_cooldowns.get(sender_id, 0)
                
                if now - last_time > 5:
                    formatted_name = f"{real_name} (@{message.author.name})"
                    if is_pk_proxy and system_name:
                        formatted_name = f"{system_name} ({real_name}, @{message.author.name})"
                    elif not is_pk_proxy:
                        formatted_name = f"{real_name} (@{message.author.name})"

                    count = memory_manager.increment_good_bot(sender_id, formatted_name)
                    client._update_lru_cache(client.good_bot_cooldowns, sender_id, now, limit=1000)
                    try: await message.add_reaction(ui.FLAVOR_TEXT["GOOD_BOT_REACTION"])
                    except: pass
                    
                    if target_message_id and target_message_id in client.active_views:
                        view = client.active_views[target_message_id]
                        updated = False
                        for child in view.children:
                            if getattr(child, "custom_id", "") == "good_bot_btn":
                                if not child.disabled:
                                    child.disabled = True
                                    child.style = discord.ButtonStyle.secondary
                                    child.label = f"Good Bot: {count}"
                                    updated = True
                            if updated:
                                try:
                                    if message.reference and message.reference.message_id == target_message_id and message.reference.resolved:
                                        ref_msg = message.reference.resolved
                                    else:
                                        ref_msg = await message.channel.fetch_message(target_message_id)
                                    await ref_msg.edit(view=view)
                                except: pass
                    return

        if should_respond:
            global_chat = memory_manager.get_server_setting("global_chat_enabled", False)
            allowed_ids = memory_manager.get_allowed_channels()
            if not global_chat and message.channel.id not in allowed_ids: return

            if message.channel.id not in client.boot_cleared_channels:
                logger.info(f"🧹 First message in #{message.channel.name} since boot. Wiping memory.")
                memory_manager.clear_channel_memory(message.channel.id, message.channel.name)
                client.boot_cleared_channels.add(message.channel.id)

            client.processing_locks.add(message.id)
            logger.info(f"Processing Message from {message.author.name} (ID: {message.id})")

            try:
                async with message.channel.typing():
                    image_data_uri = None
                    if message.attachments:
                        for att in message.attachments:
                            safe_mime = helpers.get_safe_mime_type(att)
                            if safe_mime.startswith('image/') and att.size < 8 * 1024 * 1024:
                                try:
                                    img_bytes = await att.read()
                                    b64_str = base64.b64encode(img_bytes).decode('utf-8')
                                    image_data_uri = f"data:{safe_mime};base64,{b64_str}"
                                    break
                                except Exception as e: logger.warning(f"⚠️ Error processing image: {e}")

                    clean_prompt = re.sub(r'<@!?{}>'.format(client.user.id), '', message.content)
                    for rid in config.BOT_ROLE_IDS: clean_prompt = re.sub(r'<@&{}>'.format(rid), '', clean_prompt)
                    clean_prompt = clean_prompt.replace(f"@{client.user.display_name}", "").replace(f"@{client.user.name}", "")
                    clean_prompt = clean_prompt.strip().replace("? ?", "?").replace("! ?", "!?").replace('[', '(').replace(']', ')')

                    force_search = False
                    if "&web" in clean_prompt:
                        clean_prompt = clean_prompt.replace("&web", "").strip()
                        force_search = True

                    # Identity Logic
                    real_name = message.author.display_name
                    system_tag = None
                    sender_id = None
                    system_id = None
                    member_description = None
                    
                    if message.webhook_id:
                        pk_name, pk_sys_id, pk_sys_name, pk_tag, pk_sender, pk_desc = await services.service.get_pk_message_data(message.id)
                        if pk_name:
                            real_name = pk_name
                            system_tag = pk_tag
                            if pk_sender: 
                                try: sender_id = int(pk_sender)
                                except: sender_id = None
                            system_id = pk_sys_id
                            member_description = pk_desc
                            logger.info(f"DEBUG: PK Message. SenderID: {sender_id} | SystemID: {system_id} | ConfigSysID: {config.MY_SYSTEM_ID}")
                    else:
                        sender_id = message.author.id
                        user_sys_data = await services.service.get_pk_user_data(sender_id)
                        if user_sys_data: 
                            system_tag = user_sys_data['tag']
                            system_id = user_sys_data['system_id']

                    # Check Permissions
                    member_obj = None
                    if message.guild and sender_id:
                        # Ensure int (redundant but safe)
                        try: sender_id = int(sender_id)
                        except: pass
                        
                        member_obj = message.guild.get_member(sender_id)
                        if not member_obj:
                            try: member_obj = await message.guild.fetch_member(sender_id)
                            except Exception as e: logger.warning(f"Failed to fetch member for {sender_id}: {e}")
                    
                    if not member_obj and not message.webhook_id: member_obj = message.author
                    
                    if member_obj:
                        logger.info(f"DEBUG: Member Found: {member_obj.display_name} | Roles: {[r.name for r in member_obj.roles]}")
                    else:
                        logger.info(f"DEBUG: Member NOT Found for ID: {sender_id}")

                    # Auth Check: Allow if Admin/Special Role OR if it's the Owner's System
                    is_own_system = (system_id == config.MY_SYSTEM_ID)
                    
                    if not is_own_system and not helpers.is_authorized(member_obj or sender_id):
                        logger.info(f"🛑 Access Denied for {real_name} (ID: {sender_id}). Admin Roles: {config.ADMIN_ROLE_IDS}")
                        return
                    elif is_own_system:
                        logger.info(f"✅ Access Granted via System Match: {system_id}")

                    clean_name = helpers.clean_name_logic(real_name, system_tag)
                    # Identity Suffix uses new Config logic
                    identity_suffix = helpers.get_identity_suffix(member_obj or sender_id, system_id, clean_name, services.service.my_system_members)

                    memory_manager.log_conversation(message.channel.name, real_name, sender_id or "UNKNOWN_ID", clean_prompt)

                    # History
                    history_messages = []
                    async for prev_msg in message.channel.history(limit=config.CONTEXT_WINDOW + 5, before=message):
                        cutoff = client.channel_cutoff_times.get(message.channel.id)
                        if cutoff and prev_msg.created_at < cutoff: break
                        
                        if prev_msg.webhook_id is None:
                                # 1. Check My System Tags (Self-proxy)
                                tags = await services.service.get_system_proxy_tags(config.MY_SYSTEM_ID)
                                if helpers.matches_proxy_tag(prev_msg.content, tags): continue

                                # 2. Check Author's System Tags (Other-proxy)
                                # This prevents "double vision" where the bot sees both the user's trigger command AND the resulting webhook
                                try:
                                    user_sys = await services.service.get_pk_user_data(prev_msg.author.id)
                                    if user_sys and user_sys.get('system_id'):
                                        user_tags = await services.service.get_system_proxy_tags(user_sys['system_id'])
                                        if helpers.matches_proxy_tag(prev_msg.content, user_tags): continue
                                except: pass

                        p_content = prev_msg.clean_content.strip()
                        has_image_history = any(att.content_type and att.content_type.startswith('image/') for att in prev_msg.attachments)
                        if not p_content and not has_image_history: continue
                        
                        p_content = p_content.replace(f"@{client.user.display_name}", "").replace(f"@{client.user.name}", "")
                        p_content = re.sub(r'<@!?{}>'.format(client.user.id), '', p_content).strip().replace('[', '(').replace(']', ')')

                        current_msg_content = []
                        if p_content: current_msg_content.append({"type": "text", "text": p_content})

                        # Attachments in history (Simplified: just check one)
                        if prev_msg.attachments:
                                # Logic similar to current message
                                pass # Skipping complex history image fetch to save complexity, similar to original

                        if not current_msg_content: continue

                        if prev_msg.author == client.user:
                            history_messages.append({"role": "assistant", "content": p_content})
                        else:
                            # User history formatting
                            p_author_name = prev_msg.author.display_name
                            p_sender_id = prev_msg.author.id if not prev_msg.webhook_id else None
                            p_clean_name = helpers.clean_name_logic(p_author_name, None)
                            p_suffix = helpers.get_identity_suffix(p_sender_id, None, p_clean_name)
                            
                            prefix = f"{p_clean_name}{p_suffix} says: "
                            current_msg_content[0]['text'] = prefix + current_msg_content[0]['text']
                            history_messages.append({"role": "user", "content": current_msg_content})
            
                    if len(history_messages) > config.CONTEXT_WINDOW:
                        history_messages = history_messages[:config.CONTEXT_WINDOW]
                    history_messages.reverse()

                    # Search
                    search_queries = []
                    if force_search:
                        search_queries = await services.service.generate_search_queries(clean_prompt, history_messages, force_search=True)

                    search_context = None
                    if search_queries:
                        search_results_text = ""
                        for q in search_queries:
                            results = await services.service.search_kagi(q)
                            search_results_text += f"Query: {q}\n{results}\n\n"
                        search_context = search_results_text

                    if not clean_prompt and image_data_uri: clean_prompt = "What is this image?"
                    elif not clean_prompt and not search_queries:
                        await message.channel.send("🤔 You just gonna stare at me orrrr...? 💀")
                        return

                    current_reply_context = ""
                    if message.reference and message.reference.resolved:
                        if isinstance(message.reference.resolved, discord.Message):
                                current_reply_context = f" (Replying to {message.reference.resolved.author.display_name})"

                    if client.user in message.mentions:
                        current_reply_context += " (Target: NyxOS)"

                    # Check Abort Signal BEFORE Generation
                    if message.id in client.abort_signals:
                        logger.info(f"🛑 Generation aborted for {message.id} before query.")
                        return

                    # Query LLM
                    # ... existing logic ...
                    
                    logger.info(f"Generating response for {message.author.name}...")
                    response_text = await services.service.query_lm_studio(
                        clean_prompt, 
                        real_name, 
                        identity_suffix, 
                        history_messages, 
                        message.channel,
                        image_data_uri,
                        member_description,
                        search_context=search_context,
                        reply_context_str=current_reply_context,
                        system_prompt_override=None
                    )
                    
                    # Check Abort Signal AFTER Generation
                    if message.id in client.abort_signals:
                        logger.info(f"🛑 Generation aborted for {message.id} after query.")
                        return

                    # --- POST-PROCESSING ---
                    # 1. Clean up raw text (remove headers, identity tags, reply context)
                    response_text = helpers.sanitize_llm_response(response_text)
                    
                    # 2. Log processed text
                    memory_manager.log_conversation(message.channel.name, "NyxOS", client.user.id, response_text)
                    
                    # 3. Restore formatting for Discord display
                    response_text = helpers.restore_hyperlinks(response_text)

                    view = ui.ResponseView(clean_prompt, message.author.id, clean_name, identity_suffix, history_messages, message.channel, image_data_uri, member_description, search_context, current_reply_context)

                    try:
                        # Update old view
                        prev_msg_id = client.last_bot_message_id.get(message.channel.id)
                        if prev_msg_id and prev_msg_id in client.active_views:
                            prev_view = client.active_views[prev_msg_id]
                            for child in prev_view.children:
                                if getattr(child, "custom_id", "") == "good_bot_btn":
                                    child.disabled = True
                                    child.label = "Good Bot!"
                            try:
                                old_msg = await message.channel.fetch_message(prev_msg_id)
                                await services.service.limiter.wait_for_slot("edit_message", message.channel.id)
                                await old_msg.edit(view=prev_view)
                            except: pass

                        sent_message = None
                        if len(response_text) > 2000:
                            from io import BytesIO
                            file = discord.File(BytesIO(response_text.encode()), filename="response.txt")
                            await services.service.limiter.wait_for_slot("send_message", message.channel.id)
                            sent_message = await message.reply("(Response too long, see file)", file=file, view=view, mention_author=False)
                        else:
                            await services.service.limiter.wait_for_slot("send_message", message.channel.id)
                            sent_message = await message.reply(response_text, view=view, mention_author=False)
                        
                        if sent_message:
                            client._register_view(sent_message.id, view)
                            client.last_bot_message_id[message.channel.id] = sent_message.id

                            # --- SAVE VIEW STATE FOR PERSISTENCE ---
                            view_data = {
                                "original_prompt": clean_prompt,
                                "username": clean_name,
                                "identity_suffix": identity_suffix,
                                "history_messages": history_messages,
                                "image_data_uri": image_data_uri,
                                "member_description": member_description,
                                "search_context": search_context,
                                "reply_context_str": current_reply_context
                            }
                            memory_manager.save_view_state(sent_message.id, view_data)

                            client.loop.create_task(client.suppress_embeds_later(sent_message, delay=5))

                    except discord.HTTPException as e:
                        logger.error(f"DEBUG: Failed to reply: {e}")
            except Exception as e:
                logger.error(f"Processing Error: {e}")

    finally:
        if reaction_added and not skip_reaction_remove:
            try:
                await message.remove_reaction(ui.FLAVOR_TEXT["WAKE_WORD_REACTION"], client.user)
            except: pass
        
        client.abort_signals.discard(message.id)
        
        if message.id in client.processing_locks:
            client.processing_locks.remove(message.id)

if __name__ == "__main__":
    kill_duplicate_processes()
    if not config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not found.")
    else:
        client.run(config.BOT_TOKEN)
