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
import NyxAPI

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
import backup_manager
import terminal_utils

# ==========================================
# BOT SETUP
# ==========================================

# (Process cleanup moved to NyxOSDaemon.py)

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
        
        self.terminal_channel = terminal_utils.TerminalChannel(self)

        # API Server
        self.api_server = NyxAPI.NyxAPI(self)

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

    async def handle_terminal_input(self, line):
        """Handles input from the terminal thread."""
        if not line: return
        
        # Create Mock Message
        author = terminal_utils.TerminalUser()
        channel = self.terminal_channel
        msg = terminal_utils.TerminalMessage(self, line, author, channel)
        channel.messages.append(msg)
        
        # Handle Commands (Slash to Prefix conversion)
        if line.startswith("/"):
            # Convert /command args to &command args
            msg.content = "&" + line[1:]
        else:
            # Force mention for regular chat to ensure response
            msg.mentions.append(self.user)
            
        # Inject into on_message
        # on_message handles & commands and chat logic
        try:
            await self.on_message(msg)
        except Exception as e:
            print(f"Error processing terminal input: {e}")
            traceback.print_exc()

    async def setup_hook(self):
        # Clean startup flags
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            try: os.remove(config.SHUTDOWN_FLAG_FILE)
            except: pass
            
        await services.service.start()
        self.add_view(ui.ResponseView())
        self.add_view(ui.ConsoleControlView())
        
        # Register a global/fallback StatusBarView to catch "stragglers"
        # We use None/defaults, relying on the view to pull info from the interaction
        self.add_view(ui.StatusBarView("Loading...", None, None, False))
        
        asyncio.create_task(self.heartbeat_task())

    async def handle_bar_touch(self, channel_id, message=None, user_id=None):
        """
        Centralized handler for bar interactions.
        - Registers/Adopts straggler bars into DB.
        - Updates location (message_id).
        - Syncs with Console List.
        - Syncs content with Master Bar if needed.
        """
        try:
            # --- REBOOT/SHUTDOWN GUARD ---
            # Ignore touch events if the message is in "Rebooting" or "Shutdown" state (visual only).
            # This prevents the DB from being overwritten with the temporary emojis.
            if message:
                if ui.FLAVOR_TEXT['REBOOT_EMOJI'] in message.content: return
                if ui.FLAVOR_TEXT['SHUTDOWN_EMOJI'] in message.content: return
            # -----------------------------

            # 1. Adopt/Register if missing
            if channel_id not in self.active_bars:
                logger.info(f"👻 Adopting straggler bar in {channel_id}")
                
                # Ensure allowed
                memory_manager.add_allowed_channel(channel_id)
                memory_manager.add_bar_whitelist(channel_id)
                
                # Basic defaults
                self.active_bars[channel_id] = {
                    "content": "Recovered Bar",
                    "user_id": user_id if user_id else self.user.id,
                    "message_id": message.id if message else None,
                    "checkmark_message_id": message.id if message else None,
                    "persisting": False,
                    "current_prefix": "<a:NotWatching:1301840196966285322>",
                    "has_notification": False
                }
                
                # Pull content from message if available
                if message and message.content:
                    clean_content = message.content
                    if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in clean_content:
                        clean_content = clean_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    self.active_bars[channel_id]["content"] = clean_content
                    
                    # Extract prefix from content to ensure Console Sync is accurate
                    found_prefix = None
                    for emoji in ui.BAR_PREFIX_EMOJIS:
                        if clean_content.startswith(emoji):
                            found_prefix = emoji
                            break
                    
                    if found_prefix:
                        self.active_bars[channel_id]["current_prefix"] = found_prefix

                    # Try to sync with Master Bar since we just recovered it
                    master = memory_manager.get_master_bar()
                    if master:
                         prefix = self.active_bars[channel_id].get("current_prefix", "")
                         clean_master = master.strip().replace('\n', ' ')
                         new_content = f"{prefix} {clean_master}"
                         
                         # Update State
                         self.active_bars[channel_id]["content"] = new_content
                         
                         # Edit Discord Message (Visual Sync)
                         try:
                             full_content = new_content
                             if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in message.content:
                                 chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                                 full_content = f"{new_content} {chk}"
                             
                             full_content = re.sub(r'>[ \t]+<', '><', full_content)
                             
                             await services.service.limiter.wait_for_slot("edit_message", channel_id)
                             await message.edit(content=full_content)
                             logger.info(f"✅ Synced adopted straggler in {channel_id} to Master Bar.")
                         except Exception as e:
                             logger.warning(f"Failed to visual-sync adopted bar in {channel_id}: {e}")

            # 2. Update Message ID (Movement detection) & Sync Content/Prefix
            if message:
                # Update location if changed
                if self.active_bars[channel_id].get("message_id") != message.id:
                    logger.info(f"📍 Updating location for bar in {channel_id}: {message.id}")
                    self.active_bars[channel_id]["message_id"] = message.id
                    self.active_bars[channel_id]["checkmark_message_id"] = message.id
                    memory_manager.save_channel_location(channel_id, message.id, message.id)

                # Always sync content/prefix from message on touch to ensure consistency
                if message.content:
                    clean_content = message.content
                    if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in clean_content:
                        clean_content = clean_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    
                    # Only update if different (avoid DB spam if possible, but memory update is cheap)
                    self.active_bars[channel_id]["content"] = clean_content
                    
                    for emoji in ui.BAR_PREFIX_EMOJIS:
                        if clean_content.startswith(emoji):
                            self.active_bars[channel_id]["current_prefix"] = emoji
                            break

            # 3. Clear Notification
            if self.active_bars[channel_id].get("has_notification"):
                self.active_bars[channel_id]["has_notification"] = False
                memory_manager.set_bar_notification(channel_id, False)

            # 4. Persist Current State to DB
            bar_data = self.active_bars[channel_id]
            memory_manager.save_bar(
                channel_id,
                message.guild.id if message and message.guild else None,
                bar_data["message_id"],
                bar_data["user_id"],
                bar_data["content"],
                bar_data["persisting"],
                current_prefix=bar_data.get("current_prefix"),
                has_notification=False,
                checkmark_message_id=bar_data.get("checkmark_message_id")
            )

            # 5. Sync Console
            asyncio.create_task(self.update_console_status())

        except Exception as e:
            logger.error(f"Failed to handle bar touch in {channel_id}: {e}")

    def request_bar_drop(self, channel_id):
        """Debounced drop request manager (config.BAR_DEBOUNCE_SECONDS silence timer)."""
        # Update deadline to Now + Debounce
        if not hasattr(self, "drop_deadlines"): self.drop_deadlines = {}
        self.drop_deadlines[channel_id] = time.time() + config.BAR_DEBOUNCE_SECONDS
        
        if channel_id not in self.active_drop_tasks:
            self.active_drop_tasks.add(channel_id)
            asyncio.create_task(self._process_drop_queue(channel_id))

    async def _process_drop_queue(self, channel_id):
        try:
            while True:
                now = time.time()
                deadline = self.drop_deadlines.get(channel_id, now)
                wait = deadline - now
                
                if wait > 0:
                    # Wait for the remaining silence time
                    await asyncio.sleep(wait)
                    # Check again after waking up (deadline might have moved)
                    if time.time() < self.drop_deadlines.get(channel_id, 0):
                        continue
                
                # Timer expired, safe to drop
                await self.drop_status_bar(channel_id, move_check=False, manual=False)
                break
        finally:
            self.active_drop_tasks.discard(channel_id)
            self.drop_deadlines.pop(channel_id, None)

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

    async def cleanup_recent_artifacts(self, channel, exclude_msg_id=None):
        """
        Scans the last 5 messages and deletes any bar artifacts or checkmarks.
        Used when dropping/moving bars to clear clutter.
        """
        try:
            async for msg in channel.history(limit=5):
                if msg.id == exclude_msg_id: continue
                
                should_delete = False
                if msg.author.id == self.user.id:
                    # Check Components (Buttons)
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    should_delete = True
                                    break
                            if should_delete: break
                    
                    # Check Content Prefix
                    if not should_delete and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                should_delete = True
                                break
                    
                    # Check Checkmark
                    if not should_delete and msg.content:
                        if msg.content.strip() == ui.FLAVOR_TEXT['CHECKMARK_EMOJI']:
                            should_delete = True
                
                if should_delete:
                    try: 
                        await services.service.limiter.wait_for_slot("delete_message", channel.id)
                        await msg.delete()
                    except: pass
        except Exception as e:
            logger.warning(f"Recent artifact cleanup failed: {e}")

    async def drop_status_bar(self, channel_id, move_bar=True, move_check=True, manual=True):
        # Attempt recovery if missing
        if channel_id not in self.active_bars:
             channel = self.get_channel(channel_id)
             if not channel:
                 try: channel = await self.fetch_channel(channel_id)
                 except: pass
             
             if channel:
                 # Scan for straggler
                 found_msg, found_content = await self.find_last_bar_message(channel)
                 
                 if found_msg:
                     await self.handle_bar_touch(channel_id, found_msg)
                 else:
                     return # Truly nothing found

        if channel_id not in self.active_bars: return
        
        bar_data = self.active_bars[channel_id]
        channel = self.get_channel(channel_id)
        if not channel:
            try: channel = await self.fetch_channel(channel_id)
            except: return

        # Clean up recent artifacts (duplicates/checkmarks) before proceeding
        old_bar_id = bar_data.get("message_id")
        await self.cleanup_recent_artifacts(channel, exclude_msg_id=old_bar_id)

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

        # Optimization: If bar is already at bottom
        is_at_bottom = False
        if old_bar_id:
            try:
                async for last_msg in channel.history(limit=1):
                    if last_msg.id == old_bar_id:
                        is_at_bottom = True
                        break
            except: pass

        if is_at_bottom and move_bar:
            # Already at bottom.
            # IMPROVEMENT: Instead of just returning, ensure content/check is synced via Edit.
            # This prevents "deletes and re-adds" by doing a safe in-place update.
            
            # 1. Determine desired content
            final_content = content
            if move_check: # User wants checkmark on bar
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                if chk not in final_content:
                    final_content = f"{content} {chk}"
                    final_content = re.sub(r'>[ \t]+<', '><', final_content)
                    final_content = final_content.replace(f"\n{chk}", f" {chk}")
            else:
                # User wants bar only (maybe check left behind?)
                # But if we are at bottom, we can't leave check "behind" (above).
                # So we enforce checkmark if it was already there, or strip if strictly requested?
                # "Drop All" -> move_check=True.
                # "Drop Bar" -> move_check=False.
                # If Drop Bar and at bottom, we keep it as is.
                pass

            # 2. Update Message if needed
            try:
                current_msg = await channel.fetch_message(old_bar_id)
                
                # Check if we need to edit
                # (Content diff OR View diff/refresh)
                # We always edit to refresh the View timeout/state just in case
                should_edit = (current_msg.content != final_content) or True 
                
                if should_edit:
                    view = ui.StatusBarView(final_content, bar_data["user_id"], channel_id, bar_data["persisting"])
                    await services.service.limiter.wait_for_slot("edit_message", channel_id)
                    await current_msg.edit(content=final_content, view=view)
                    
                    # Update DB state if checkmark merged
                    if move_check:
                         self.active_bars[channel_id]["checkmark_message_id"] = old_bar_id
                         # Clear old checkmark if it was separate?
                         if old_check_id and old_check_id != old_bar_id:
                             try:
                                 old_chk = await channel.fetch_message(old_check_id)
                                 await old_chk.delete()
                             except: pass

                    # Sync DB
                    memory_manager.save_bar(
                        channel_id, 
                        channel.guild.id if channel.guild else None,
                        old_bar_id,
                        bar_data["user_id"],
                        final_content,
                        bar_data["persisting"],
                        current_prefix=bar_data.get("current_prefix"),
                        has_notification=False,
                        checkmark_message_id=self.active_bars[channel_id]["checkmark_message_id"]
                    )
            except Exception as e:
                logger.warning(f"Failed in-place update at bottom: {e}")
            
            return # Stop here, don't drop/re-add

        # Fix: If moving check only (move_bar=False), and check is already merged on bar, do nothing.
        if not move_bar and move_check:
             if old_check_id and old_bar_id and old_check_id == old_bar_id:
                  move_check = False

        # Reset Notification Flag on Drop
        if manual and channel_id in self.active_bars:
             self.active_bars[channel_id]["has_notification"] = False
             memory_manager.set_bar_notification(channel_id, False)
             asyncio.create_task(self.update_console_status())

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
                        self.pending_drops.add(old_msg.id)
                        await old_msg.delete()
                except: pass
            
            # Prepare Content
            content_to_send = content
            if move_check:
                # Append checkmark immediately to save API call
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                content_to_send = f"{content} {chk}"
                content_to_send = re.sub(r'>[ \t]+<', '><', content_to_send)
                content_to_send = content_to_send.replace(f"\n{chk}", f" {chk}")

            # Send new bar
            view = ui.StatusBarView(content_to_send, bar_data["user_id"], channel_id, bar_data["persisting"])
            try:
                await services.service.limiter.wait_for_slot("send_message", channel_id)
                new_bar_msg = await channel.send(content_to_send, view=view)
                
                # Update State
                self.active_bars[channel_id]["message_id"] = new_bar_msg.id
                self._register_bar_message(channel_id, new_bar_msg.id, view)
                
                # If we included checkmark, update ID immediately and disable further move_check logic
                if move_check:
                    self.active_bars[channel_id]["checkmark_message_id"] = new_bar_msg.id
                    move_check = False # Done
                else:
                     # Checkmark was left behind or didn't move.
                     # If we split (left behind), check_final_id should be old_bar_id (which became checkmark)
                     if old_bar_id == old_check_id:
                         self.active_bars[channel_id]["checkmark_message_id"] = old_bar_id
            except Exception as e:
                logger.error(f"Failed to send bar: {e}")
                return
        else:
            # If not moving bar, we need the object to know where to put the check (if separate?)
            if old_bar_id:
                try:
                    new_bar_msg = await channel.fetch_message(old_bar_id)
                except: pass
                
        # 2. Handle Checkmark Movement (Only if not handled above)
        if move_check:
            # Delete old check
            if old_check_id and old_check_id != old_bar_id: 
                 try:
                    old_chk = await channel.fetch_message(old_check_id)
                    await old_chk.delete()
                 except: pass
            elif old_check_id and old_check_id == old_bar_id and not move_bar:
                 # If we are not moving the bar, but moving the check, and they were merged:
                 # The bar message stays, but we need to edit it to remove the checkmark
                 # This is handled by the "SPLIT" logic in move_bar block above, OR we need to do it here if move_bar was False.
                 try:
                    old_chk_msg = await channel.fetch_message(old_check_id)
                    content_no_check = old_chk_msg.content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    # Just edit, don't delete
                    await old_chk_msg.edit(content=content_no_check)
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
            self.active_bars[channel_id]["persisting"],
            current_prefix=self.active_bars[channel_id].get("current_prefix"),
            has_notification=self.active_bars[channel_id].get("has_notification", False),
            checkmark_message_id=check_final_id
        )
        
        # Touch Event
        asyncio.create_task(self.handle_bar_touch(channel_id))

    async def restore_all_bars(self):
        """
        Restores all bars to their previous state (Normal Mode).
        Returns the number of bars restored.
        """
        logger.info("🔄 Restoring all bars to previous state...")
        count = 0
        
        # 1. Reset System Mode
        memory_manager.set_server_setting("system_mode", "normal")
        
        # 2. Iterate Active Bars
        # Use copy of items since we might modify active_bars indirectly (though mostly in-place updates)
        for cid, bar_data in list(self.active_bars.items()):
            try:
                # Retrieve Previous State
                prev_state = memory_manager.get_previous_state(cid)
                if not prev_state:
                    # If no history, reconstruct a "Normal" state
                    current_content = bar_data.get("content", "")
                    clean_content = current_content
                    for emoji in ui.BAR_PREFIX_EMOJIS:
                        if clean_content.startswith(emoji):
                            clean_content = clean_content[len(emoji):].strip()
                            break
                    
                    default_prefix = ui.BAR_PREFIX_EMOJIS[0]
                    prev_state = {
                        "content": f"{default_prefix} {clean_content}",
                        "current_prefix": default_prefix,
                        "has_notification": False,
                        "persisting": bar_data.get("persisting", False),
                        "user_id": bar_data.get("user_id", self.user.id)
                    }
                
                # Prepare Content
                final_content = prev_state.get("content", "")
                prefix = prev_state.get("current_prefix")
                
                # Get Message
                msg_id = bar_data.get("message_id")
                if not msg_id: continue
                
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: continue
                
                try:
                    msg = await ch.fetch_message(msg_id)
                except (discord.NotFound, discord.Forbidden):
                    continue
                
                # Handle Checkmark
                check_id = bar_data.get("checkmark_message_id")
                has_merged_check = (check_id == msg_id)
                
                content_to_send = final_content
                if has_merged_check:
                    chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                    if chk not in content_to_send:
                        content_to_send = f"{content_to_send} {chk}"
                        content_to_send = re.sub(r'>[ \t]+<', '><', content_to_send)
                
                # Apply Edit
                view = ui.StatusBarView(content_to_send, prev_state["user_id"], cid, prev_state.get("persisting", False))
                await services.service.limiter.wait_for_slot("edit_message", cid)
                await msg.edit(content=content_to_send, view=view)
                
                # Update Memory
                self.active_bars[cid]["content"] = final_content
                self.active_bars[cid]["current_prefix"] = prefix
                self.active_bars[cid]["has_notification"] = prev_state.get("has_notification", False)
                self._register_bar_message(cid, msg_id, view)
                
                # Update DB
                memory_manager.save_bar(
                    cid, 
                    ch.guild.id, 
                    msg_id, 
                    prev_state["user_id"], 
                    final_content, 
                    prev_state.get("persisting", False),
                    current_prefix=prefix,
                    has_notification=prev_state.get("has_notification", False),
                    checkmark_message_id=check_id
                )
                count += 1
                
            except Exception as e:
                logger.warning(f"Failed to restore bar {cid}: {e}")
        
        # Sync Console
        await self.update_console_status()
        
        return count

    async def sleep_all_bars(self):
        """
        Puts all active bars to sleep (Toggle).
        If already sleeping, restores previous state.
        """
        # 0. Check Toggle
        current_mode = memory_manager.get_server_setting("system_mode", "normal")
        if current_mode == "sleep":
             return await self.restore_all_bars()
        
        memory_manager.set_server_setting("system_mode", "sleep")

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
                    # Save state ONLY if coming from Normal mode
                    if current_mode == "normal":
                        memory_manager.save_previous_state(cid, bar_data)
                else:
                    # Remnant recovery
                    found_msg, found = await self.find_last_bar_message(ch)
                    
                    if found_msg and cid not in self.active_bars:
                         await self.handle_bar_touch(cid, found_msg)
                         # Re-fetch bar data after touch
                         if cid in self.active_bars:
                             bar_data = self.active_bars[cid]

                    if found:
                        current_content = found
                        # Strip checkmark
                        if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in current_content:
                            current_content = current_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    else:
                        return False

                # Construct New Content
                clean_middle = current_content
                found_prefix = None
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if clean_middle.startswith(emoji):
                        found_prefix = emoji
                        clean_middle = clean_middle[len(emoji):].strip()
                        break
                
                # Set DB Sleep State (Persist original prefix)
                memory_manager.set_bar_sleeping(cid, True, original_prefix=found_prefix)

                new_base_content = f"{sleeping_emoji}{clean_middle.strip()}"
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
                    has_merged_check = (check_id == msg.id)
                    
                    final_content = new_base_content
                    if has_merged_check:
                        chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                        if chk not in final_content:
                            final_content = f"{final_content}{chk}"
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
                            "current_prefix": sleeping_emoji,
                            "has_notification": False
                        }
                        self._register_bar_message(cid, msg.id, view)
                        memory_manager.save_bar(
                            cid, 
                            ch.guild.id, 
                            msg.id, 
                            bar_data["user_id"], 
                            new_base_content, 
                            persisting, 
                            current_prefix=sleeping_emoji, 
                            has_notification=False, 
                            checkmark_message_id=msg.id
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"Sleep edit failed in {cid}, falling back to wipe/send: {e}")

                # FALLBACK: Wipe & Replace
                await self.wipe_channel_bars(ch)

                # Checkmark included in new send? usually drop/send includes it.
                # But here we are constructing base content.
                # Let's standardise: always include checkmark on new send.
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                send_content = f"{new_base_content}{chk}"
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
                    "current_prefix": sleeping_emoji,
                    "has_notification": False
                }
                self._register_bar_message(cid, new_msg.id, view)
                
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting, current_prefix=sleeping_emoji, has_notification=False, checkmark_message_id=new_msg.id)
                return True

            except Exception as e:
                logger.error(f"Sleep error in {cid}: {e}")
                return False

        tasks = []
        for cid, bar in targets:
            tasks.append(process_bar(cid, bar))
        
        results = await asyncio.gather(*tasks)
        
        # Sync Console
        await self.ensure_bar_consistency()
        
        return sum(1 for r in results if r)

    async def idle_all_bars(self):
        """
        Sets all active bars and remnants in allowed channels to IDLE (Not Watching) (Reset).
        Forces Speed 0. Does not save previous state.
        """
        # Set Mode
        memory_manager.set_server_setting("system_mode", "idle")

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
                    found_msg, found = await self.find_last_bar_message(ch)
                    
                    if found_msg and cid not in self.active_bars:
                         await self.handle_bar_touch(cid, found_msg)
                         if cid in self.active_bars:
                             bar_data = self.active_bars[cid]

                    if found:
                        current_content = found
                        if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in current_content:
                            current_content = current_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                    else:
                        return False

                # Construct New Content (Strip old prefix)
                clean_middle = current_content
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if clean_middle.startswith(emoji):
                        clean_middle = clean_middle[len(emoji):].strip()
                        break
                
                # RESET: Force NotWatching Prefix
                new_base_content = f"{idle_emoji}{clean_middle.strip()}"
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
                    has_merged_check = (check_id == msg.id)
                    
                    final_content = new_base_content
                    if has_merged_check:
                        chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                        if chk not in final_content:
                            final_content = f"{final_content}{chk}"
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
                            "current_prefix": idle_emoji,
                            "has_notification": False
                        }
                        self._register_bar_message(cid, msg.id, view)
                        memory_manager.save_bar(cid, ch.guild.id, msg.id, bar_data["user_id"], new_base_content, persisting, current_prefix=idle_emoji, has_notification=False, checkmark_message_id=msg.id)
                        return True
                    except Exception as e:
                        logger.warning(f"Idle edit failed in {cid}, falling back to wipe/send: {e}")

                # FALLBACK: Wipe & Replace
                await self.wipe_channel_bars(ch)
                
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                send_content = f"{new_base_content}{chk}"
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
                    "current_prefix": idle_emoji,
                    "has_notification": False
                }
                self._register_bar_message(cid, new_msg.id, view)
                
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting, current_prefix=idle_emoji, has_notification=False, checkmark_message_id=new_msg.id)
                return True

            except Exception as e:
                logger.error(f"Idle error in {cid}: {e}")
                return False

        tasks = []
        for cid, bar in targets:
            tasks.append(process_bar(cid, bar))
        
        results = await asyncio.gather(*tasks)
        
        # Sync Console
        await self.ensure_bar_consistency()

        return sum(1 for r in results if r)

    async def global_update_bars(self, new_text_suffix):
        """
        Updates the content (suffix) of all active bars while preserving their current status emoji.
        Also updates the Master Bar (DB + Console Channel) to ensure consistency.
        Does NOT move the bar (edits in place).
        """
        # 1. Update Master Bar in Database (Source of Truth)
        clean_suffix = new_text_suffix.strip().replace('\n', ' ')
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
                    self.active_bars[cid]["has_notification"] = False
                    self._register_bar_message(cid, msg_id, view)
                    
                    memory_manager.save_bar(
                        cid, 
                        ch.guild.id, 
                        msg_id, 
                        bar_data["user_id"], 
                        final_content, 
                        bar_data.get("persisting", False),
                        has_notification=False,
                        checkmark_message_id=msg_id # Edit in place, checkmark merged if present
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
        Wakes up all bars by restoring their previous state or defaulting to Speed 0.
        """
        allowed_channels = memory_manager.get_allowed_channels()
        default_prefix = "<a:NotWatching:1301840196966285322>" # Speed 0

        # Reset System Mode
        memory_manager.set_server_setting("system_mode", "normal")

        async def process_wake(cid):
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return False

                # 1. Find Content (Scan)
                found_msg, found_content = await self.find_last_bar_message(ch)
                
                # Adopt if found via scan but missing in DB
                if found_msg and cid not in self.active_bars:
                     await self.handle_bar_touch(cid, found_msg)

                if not found_content:
                    if cid in self.active_bars:
                        found_content = self.active_bars[cid]["content"]
                
                if not found_content: return False

                # 2. Determine Target Prefix
                # Try to get from previous state first
                prev_state = memory_manager.get_previous_state(cid)
                target_prefix = default_prefix
                
                if prev_state and prev_state.get('current_prefix'):
                    target_prefix = prev_state.get('current_prefix')
                elif cid in self.active_bars and self.active_bars[cid].get('original_prefix'):
                    # Fallback to original_prefix stored during sleep
                    target_prefix = self.active_bars[cid].get('original_prefix')

                # 3. Clean Content (Strip existing prefix and checkmark)
                clean_content = found_content
                if ui.FLAVOR_TEXT['CHECKMARK_EMOJI'] in clean_content:
                    clean_content = clean_content.replace(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], "").strip()
                
                # Strip known prefixes
                # We iterate all known prefixes (including sleep/idle)
                all_prefixes = ui.BAR_PREFIX_EMOJIS + ["<a:Sleeping:1312772391759249410>", "<a:NotWatching:1301840196966285322>"]
                for emoji in all_prefixes:
                    if clean_content.startswith(emoji):
                        clean_content = clean_content[len(emoji):].strip()
                        break # Only strip one prefix
                
                # 4. Construct New Content
                new_base_content = f"{target_prefix} {clean_content}"
                new_base_content = re.sub(r'>[ \t]+<', '><', new_base_content)
                
                # Capture Persistence
                persisting = False
                if cid in self.active_bars:
                    persisting = self.active_bars[cid].get("persisting", False)

                # Attempt Edit In-Place
                # Use found_msg if available, otherwise try to fetch from DB ID
                msg = found_msg
                bar_data = self.active_bars.get(cid)
                
                if not msg and bar_data:
                    msg_id = bar_data.get("message_id")
                    if msg_id:
                         try: msg = await ch.fetch_message(msg_id)
                         except: pass
                
                if not msg:
                    pass # We already scanned with find_last_bar_message above. If not found there, we proceed to Wipe & Send.

                if msg:
                     # EDIT
                     check_id = bar_data.get("checkmark_message_id") if bar_data else msg.id
                     has_merged_check = (check_id == msg.id)
                     
                     final_content = new_base_content
                     chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
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
                            "persisting": persisting,
                            "current_prefix": target_prefix, # Update active prefix
                            "has_notification": False
                         }
                         self._register_bar_message(cid, msg.id, view)
                         memory_manager.save_bar(cid, ch.guild.id, msg.id, self.user.id, new_base_content, persisting, current_prefix=target_prefix, has_notification=False, checkmark_message_id=msg.id)
                         
                         # Clear sleeping state
                         memory_manager.set_bar_sleeping(cid, False)
                         return True
                     except Exception:
                         pass # Fallthrough

                # 3. Wipe & Send
                await self.wipe_channel_bars(ch)
                
                chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                send_content = f"{new_base_content} {chk}"
                send_content = re.sub(r'>[ \t]+<', '><', send_content)
                send_content = send_content.replace(f"\n{chk}", f" {chk}")

                view = ui.StatusBarView(send_content, self.user.id, cid, persisting)
                await services.service.limiter.wait_for_slot("send_message", cid)
                new_msg = await ch.send(send_content, view=view)
                
                self.active_bars[cid] = {
                    "content": new_base_content,
                    "user_id": self.user.id,
                    "message_id": new_msg.id,
                    "checkmark_message_id": new_msg.id,
                    "persisting": persisting,
                    "current_prefix": target_prefix,
                    "has_notification": False
                }
                self._register_bar_message(cid, new_msg.id, view)
                memory_manager.save_bar(cid, ch.guild.id, new_msg.id, self.user.id, new_base_content, persisting, current_prefix=target_prefix, has_notification=False, checkmark_message_id=new_msg.id)
                memory_manager.set_bar_sleeping(cid, False)
                return True

            except Exception as e:
                 logger.error(f"Awake error in {cid}: {e}")
                 return False

        tasks = []
        for cid in allowed_channels:
            tasks.append(process_wake(cid))
        
        results = await asyncio.gather(*tasks)
        
        # Sync Console
        await self.update_console_status()
        
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
            self.active_bars[cid]["has_notification"] = False
            
            async def update_msg(cid, msg_id, new_cont):
                try:
                    ch = self.get_channel(cid) or await self.fetch_channel(cid)
                    msg = await ch.fetch_message(msg_id)
                    full = f"{new_cont} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
                    full = re.sub(r'>[ \t]+<', '><', full)
                    await msg.edit(content=full)
                except: pass
            
            asyncio.create_task(update_msg(cid, bar["message_id"], new_content))
            
            # Update DB with new prefix
            memory_manager.save_bar(
                cid, 
                bar.get("guild_id"),
                bar["message_id"],
                bar["user_id"],
                new_content,
                bar.get("persisting", False),
                current_prefix=target_emoji,
                has_notification=False,
                checkmark_message_id=bar.get("checkmark_message_id")
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
        
        master_content = master_content.strip().replace('\n', ' ')

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

                # ANGEL GUARD: Ignore Angel/Dark Angel bars
                clean_current = current_content.replace(' \n', '\n') # Normalize line breaks
                if clean_current == ui.ANGEL_CONTENT or clean_current == ui.DARK_ANGEL_CONTENT:
                    return False

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
                    self.active_bars[cid]["has_notification"] = False
                    self._register_bar_message(cid, msg_id, view)
                    
                    memory_manager.save_bar(
                        cid, 
                        ch.guild.id, 
                        msg_id, 
                        bar_data["user_id"], 
                        new_base_content, 
                        bar_data.get("persisting", False),
                        has_notification=False,
                        checkmark_message_id=check_id if check_id else msg_id
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

    async def verify_and_restore_bars(self):
        """
        Verifies existence of active bars via API and restores their views.
        Only removes invalid entries if the message is definitely deleted (NotFound).
        Tolerates network/permission errors by keeping the bar in DB/Memory.
        """
        logger.info("🔄 Verifying and restoring status bar views...")
        count = 0
        to_remove = []
        
        # Iterate over a copy since we might modify the dict
        for channel_id, bar_data in list(self.active_bars.items()):
            # --- SANITY CHECK ---
            if isinstance(channel_id, int) and channel_id < 1000000000000000:
                logger.warning(f"⚠️ Found invalid Channel ID {channel_id} in DB. Purging.")
                to_remove.append(channel_id)
                continue
            # --------------------

            # --- REBOOT/SHUTDOWN RESTORATION LOGIC ---
            # If DB says "Rebooting" or "Shutdown", we must switch back to "Normal" (Original Prefix)
            # This happens because we now persist the reboot state to update the console.
            current_db_prefix = bar_data.get("current_prefix")
            reboot_emojis = [ui.FLAVOR_TEXT['REBOOT_EMOJI'], ui.FLAVOR_TEXT['SHUTDOWN_EMOJI']]
            
            if current_db_prefix in reboot_emojis:
                # Fetch previous state JSON to get original prefix
                prev_state = memory_manager.get_previous_state(channel_id)
                original_prefix = prev_state.get("original_prefix") if prev_state else None
                
                if original_prefix:
                    logger.info(f"🔄 Waking up Bar {channel_id} from {current_db_prefix} -> {original_prefix}")
                    
                    # Restore Content
                    content = bar_data.get("content", "")
                    # Strip the reboot emoji
                    if content.startswith(current_db_prefix):
                        content = content[len(current_db_prefix):].strip()
                    
                    # Apply original prefix
                    new_content = f"{original_prefix} {content}"
                    new_content = re.sub(r'>[ \t]+<', '><', new_content)
                    
                    # Update Internal State
                    bar_data["current_prefix"] = original_prefix
                    bar_data["content"] = new_content
                    
                    # Update DB immediately (Clears previous_state effectively by not setting it, or we should explicity clear it?)
                    # save_bar doesn't touch previous_state. We should probably clear it separately?
                    # Actually, leaving it is fine, it gets overwritten next time we save state.
                    memory_manager.save_bar(
                        channel_id,
                        bar_data.get("guild_id"),
                        bar_data.get("message_id"),
                        bar_data.get("user_id"),
                        new_content,
                        bar_data.get("persisting", False),
                        current_prefix=original_prefix,
                        has_notification=bar_data.get("has_notification", False),
                        checkmark_message_id=bar_data.get("checkmark_message_id")
                    )
                else:
                    # If we lost the original prefix, default to Idle/NotWatching
                    default_prefix = "<a:NotWatching:1301840196966285322>"
                    logger.warning(f"⚠️ Bar {channel_id} stuck in Reboot/Shutdown with no original prefix. Defaulting to Idle.")
                    
                    content = bar_data.get("content", "").replace(current_db_prefix, "").strip()
                    new_content = f"{default_prefix} {content}"
                    
                    bar_data["current_prefix"] = default_prefix
                    bar_data["content"] = new_content
                    
                    memory_manager.save_bar(
                        channel_id,
                        bar_data.get("guild_id"),
                        bar_data.get("message_id"),
                        bar_data.get("user_id"),
                        new_content,
                        bar_data.get("persisting", False),
                        current_prefix=default_prefix,
                        has_notification=bar_data.get("has_notification", False),
                        checkmark_message_id=bar_data.get("checkmark_message_id")
                    )
            # -----------------------------------------

            msg_id = bar_data.get("message_id")
            if not msg_id:
                # No message ID -> Cannot restore
                logger.warning(f"⚠️ Bar {channel_id} has no message ID in DB. Marking for removal.")
                to_remove.append(channel_id)
                continue
            
            # Try to restore view first (optimistic)
            try:
                view = ui.StatusBarView(
                    bar_data.get("content", ""),
                    bar_data.get("user_id", self.user.id),
                    channel_id,
                    bar_data.get("persisting", False)
                )
                
                # We attempt to fetch message to verify existence
                channel = self.get_channel(channel_id)
                if not channel:
                    try: channel = await self.fetch_channel(channel_id)
                    except: pass
                
                if channel:
                    try:
                        msg = await channel.fetch_message(msg_id)
                        # Valid -> Register
                        self.add_view(view, message_id=msg_id)
                        self._register_view(msg_id, view)
                        
                        # --- SYNC FIX: Update DB from Live Message OR Update Message from DB ---
                        # Now that we've fixed the DB (above), we check if the live message needs update.
                        # If live message still shows "Rebooting" (because we just updated DB to Normal),
                        # the logic below will catch the mismatch and update the message?
                        # Wait, existing logic updates DB from Message if mismatch.
                        # "if found_prefix and found_prefix != bar_data.get('current_prefix'):"
                        # If Message=Reboot, DB=Normal (just fixed). Mismatch!
                        # "if found_prefix == REBOOT_EMOJI ... RESTORE Discord message to match DB."
                        # PERFECT. The existing logic I wrote previously handles exactly this:
                        # It sees Discord is "Rebooting", DB is "Normal", and edits Discord to match DB.
                        
                        if msg.content:
                            found_prefix = None
                            clean_cont = msg.content.strip()
                            for emoji in ui.BAR_PREFIX_EMOJIS:
                                if clean_cont.startswith(emoji):
                                    found_prefix = emoji
                                    break
                            
                            if found_prefix and found_prefix != bar_data.get("current_prefix"):
                                if found_prefix == ui.FLAVOR_TEXT['REBOOT_EMOJI'] or found_prefix == ui.FLAVOR_TEXT['SHUTDOWN_EMOJI']:
                                    # RECOVERY: Discord is in "Reboot/Shutdown Mode" (Visual), but DB has the "True" state.
                                    # RESTORE Discord message to match DB.
                                    logger.info(f"🔄 Restoring Bar {channel_id} from Reboot/Shutdown state...")
                                    
                                    true_content = bar_data.get("content", "Loading...")
                                    # Ensure checkmark if needed
                                    check_id = bar_data.get("checkmark_message_id")
                                    has_merged_check = (check_id == msg.id)
                                    
                                    content_to_send = true_content
                                    if has_merged_check:
                                        chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                                        if chk not in content_to_send:
                                            content_to_send = f"{content_to_send} {chk}"
                                            content_to_send = re.sub(r'>[ \t]+<', '><', content_to_send)
                                    
                                    try:
                                        # Re-apply View (Buttons)
                                        await msg.edit(content=content_to_send, view=view)
                                    except Exception as e:
                                        logger.warning(f"Failed to restore bar {channel_id}: {e}")
                                
                                else:
                                    # Normal Sync: Discord is newer/correct, update DB
                                    logger.info(f"🔄 Syncing Bar {channel_id} from Live Message: {found_prefix}")
                                    self.active_bars[channel_id]["current_prefix"] = found_prefix
                                    self.active_bars[channel_id]["content"] = clean_cont
                                    
                                    memory_manager.save_bar(
                                        channel_id,
                                        msg.guild.id,
                                        msg.id,
                                        bar_data["user_id"],
                                        clean_cont,
                                        bar_data.get("persisting", False),
                                        current_prefix=found_prefix,
                                        has_notification=bar_data.get("has_notification", False),
                                        checkmark_message_id=bar_data.get("checkmark_message_id")
                                    )
                        # ---------------------------------------------

                        count += 1
                    except discord.NotFound:
                        # Message is GONE -> Attempt Auto-Recovery
                        logger.warning(f"🗑️ Bar message {msg_id} in {channel_id} not found. Attempting recovery...")
                        found_replacement = False
                        
                        # Scan recent history for a valid bar
                        try:
                            async for hist_msg in channel.history(limit=10):
                                if hist_msg.author.id == self.user.id:
                                    # Simple check: components?
                                    # Or just content prefix?
                                    is_bar = False
                                    if hist_msg.components:
                                         for row in hist_msg.components:
                                             for child in row.children:
                                                 if getattr(child, "custom_id", "").startswith("bar_"):
                                                     is_bar = True; break
                                    
                                    if is_bar:
                                        # Found one! Adopt it.
                                        logger.info(f"♻️ Recovered bar in {channel_id}: {hist_msg.id}")
                                        self.active_bars[channel_id]["message_id"] = hist_msg.id
                                        self.active_bars[channel_id]["checkmark_message_id"] = hist_msg.id
                                        # Update DB
                                        memory_manager.update_bar_message_id(channel_id, hist_msg.id)
                                        
                                        # Register
                                        self.add_view(view, message_id=hist_msg.id)
                                        self._register_view(hist_msg.id, view)
                                        count += 1
                                        found_replacement = True
                                        break
                        except Exception as ex:
                             logger.error(f"Recovery failed: {ex}")

                        if not found_replacement:
                            logger.warning(f"❌ Recovery failed for {channel_id}. Removing bar.")
                            to_remove.append(channel_id)
                    except discord.Forbidden:
                        # Permission issue -> Keep in DB, maybe permissions come back?
                        logger.warning(f"🚫 No access to message {msg_id} in {channel_id}. Keeping in DB.")
                        # Still register view in case we gain access? (Can't without message obj usually, but add_view needs ID)
                        self.add_view(view, message_id=msg_id)
                        self._register_view(msg_id, view)
                        count += 1
                    except discord.HTTPException as e:
                        # Network/Server Error -> Keep in DB!
                        logger.warning(f"⚠️ HTTP Error checking bar {msg_id} in {channel_id}: {e}. Keeping in DB.")
                        # Register blindly hoping it exists
                        self.add_view(view, message_id=msg_id)
                        self._register_view(msg_id, view)
                        count += 1
                else:
                    # Channel not found/accessible -> Keep in DB (might be temporary outage)
                    # But if it's channel 123, it's invalid. (Handled at start)
                    logger.warning(f"⚠️ Channel {channel_id} inaccessible. Keeping bar in DB.")
                    # Can't register view without knowing if channel exists really, but let's try
                    self.add_view(view, message_id=msg_id)
                    self._register_view(msg_id, view)
                    count += 1
                    
            except Exception as e:
                logger.error(f"Failed to verify/restore view for {channel_id}: {e}")

        # Cleanup Invalid Bars
        for cid in to_remove:
            if cid in self.active_bars:
                del self.active_bars[cid]
                memory_manager.delete_bar(cid)
                memory_manager.remove_bar_whitelist(cid)
                
        logger.info(f"✅ Verified and Restored {count} status bar views.")

    async def ensure_bar_consistency(self):
        """
        Helper: Checks if 'current_prefix' matches the actual content prefix for all active bars.
        Updates internal state and DB if mismatched, then triggers console update.
        """
        logger.info("🔧 Verifying bar consistency (Prefix Check)...")
        updated_count = 0
        
        for cid, bar_data in self.active_bars.items():
            content = bar_data.get("content", "").strip()
            stored_prefix = bar_data.get("current_prefix", "")
            
            found_prefix = None
            for emoji in ui.BAR_PREFIX_EMOJIS:
                if content.startswith(emoji):
                    found_prefix = emoji
                    break
            
            if found_prefix and found_prefix != stored_prefix:
                # Mismatch detected!
                logger.info(f"⚠️ Prefix mismatch in {cid}. Stored: {stored_prefix}, Found: {found_prefix}. Fixing.")
                self.active_bars[cid]["current_prefix"] = found_prefix
                
                # Update DB (Partial update if possible, or full save)
                # We re-save the bar.
                memory_manager.save_bar(
                    cid, 
                    bar_data.get("guild_id"),
                    bar_data.get("message_id"),
                    bar_data.get("user_id"),
                    content,
                    bar_data.get("persisting"),
                    current_prefix=found_prefix, # The fix
                    has_notification=bar_data.get("has_notification"),
                    checkmark_message_id=bar_data.get("checkmark_message_id")
                )
                updated_count += 1
        
        if updated_count > 0:
            logger.info(f"✅ Fixed {updated_count} inconsistent bar prefixes.")
        
        await self.update_console_status()

    async def initialize_console_channel(self, t_ch):
        """Initializes or updates the console messages (Header, Master, Uplinks, Event Log)."""
        if not t_ch: return

        master_content = memory_manager.get_master_bar() or "NyxOS Uplink Active"
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        startup_header_text = f"{ui.FLAVOR_TEXT['STARTUP_HEADER']}\n{ui.FLAVOR_TEXT['STARTUP_SUB_DONE']}\n{divider}"
        event_log_text = f"{divider}\n# System Events"

        # 1. Fetch existing messages
        msgs = []
        async for m in t_ch.history(limit=20):
            if m.author.id == self.user.id:
                msgs.append(m)
        msgs.sort(key=lambda x: x.created_at)

        h_msg, bar_msg, list_msgs, event_msg = None, None, [], None
        valid_structure = False

        # 2. Sandwich Detection
        if len(msgs) >= 3: # Need at least Header, Master, and something else (List or Event)
            h_msg = msgs[0]
            bar_msg = msgs[1]
            
            # Search for Event Log (from end backwards, or just scan)
            # The Event Log should contain the divider and "# System Events"
            for i in range(2, len(msgs)):
                if divider in msgs[i].content and "# System Events" in msgs[i].content:
                    event_msg = msgs[i]
                    # Everything between 1 and i is List
                    list_msgs = msgs[2:i]
                    break
            
            # If we found an event message, we have a valid sandwich (even if list is empty/missing, though unlikely)
            if event_msg:
                if not list_msgs:
                     # If list is missing (e.g. Header, Bar, Event), create one
                     # This implies we insert a message? Inserting is hard in Discord (can't).
                     # We must wipe if we can't preserve order.
                     valid_structure = False
                else:
                     valid_structure = True
            else:
                # No Event Log found. Check if the LAST message is the List?
                # If we are upgrading from 3-msg system, we won't find Event Log.
                # We should treat all remaining as List, and Append Event Log.
                list_msgs = msgs[2:]
                valid_structure = False # Force append of event log?
                # Actually, if we just append, it's fine. But let's rely on wipe/rebuild for cleaner upgrade.
                pass

        if valid_structure:
             pass # Good to go
        else:
            # Invalid or Upgrade -> Wipe and Recreate
            try: await t_ch.purge(limit=100)
            except: pass
            
            h_msg = await t_ch.send(startup_header_text)
            bar_msg = await t_ch.send(master_content)
            list_msgs = [await t_ch.send(f"{divider}\nLoading Uplinks...", view=ui.ConsoleControlView())]
            event_msg = await t_ch.send(event_log_text)

        # 3. Update Content
        if h_msg.content != startup_header_text:
            try: await h_msg.edit(content=startup_header_text)
            except: pass
            
        if bar_msg.content != master_content:
            try: await bar_msg.edit(content=master_content)
            except: pass
            
        if event_msg.content != event_log_text:
            try: await event_msg.edit(content=event_log_text)
            except: pass

        # 4. Register references
        self.startup_header_msg = h_msg
        self.startup_bar_msg = bar_msg
        self.console_progress_msgs = list_msgs
        self.event_log_msg = event_msg

    async def on_ready(self):
        logger.info('# ==========================================')
        logger.info('#                NyxOS v2.0')
        logger.info('#         Lovingly made by Calyptra')
        logger.info('#       https://temple.HyperSystem.xyz')    
        logger.info('# ==========================================')
        logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
        
        # Debug: List commands in tree
        cmds = [c.name for c in self.tree.get_commands()]
        logger.info(f"DEBUG: Registered Slash Commands: {cmds}")
        if "nukedatabase" not in cmds:
            logger.error("CRITICAL: 'nukedatabase' command NOT found in tree!")
        
        logger.info(f'Targeting LM Studio at: {config.LM_STUDIO_URL}')
        
        # Load Active Bars from DB (Internal state mostly, but we override content via scan)
        self.active_bars = memory_manager.get_all_bars()
        logger.info(f"Active Bars loaded (DB): {len(self.active_bars)}")
        
        # Restore Views for Persistence
        await self.verify_and_restore_bars()
        
        # Check for restart metadata
        restart_data = None
        if os.path.exists(config.RESTART_META_FILE):
            try:
                with open(config.RESTART_META_FILE, "r") as f:
                    restart_data = json.load(f)
                os.remove(config.RESTART_META_FILE)
            except: pass

        # Load Whitelist EARLY to avoid UnboundLocalError
        bar_whitelist = memory_manager.get_bar_whitelist()
        allowed_channels = memory_manager.get_allowed_channels()
        
        # --- STARTUP PROGRESS MESSAGE ---
        target_channels = set()
        if config.STARTUP_CHANNEL_ID:
            target_channels.add(config.STARTUP_CHANNEL_ID)
        if restart_data and restart_data.get("channel_id"):
            target_channels.add(restart_data.get("channel_id"))
        
        # Construct Texts
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        startup_header_text = f"{ui.FLAVOR_TEXT['STARTUP_HEADER']}\n{ui.FLAVOR_TEXT['STARTUP_SUB_DONE']}\n{divider}"
        
        # Just ensure the header exists and is updated. No "Scanning" body.
        for t_id in target_channels:
            try:
                t_ch = self.get_channel(t_id) or await self.fetch_channel(t_id)
                if not t_ch: continue
                
                await self.initialize_console_channel(t_ch)
                
            except Exception as e:
                logger.error(f"❌ Failed to init startup messages in {t_id}: {e}")

        # --- PHASE 1: INITIALIZATION ---
        
        # Populate Active Uplinks from DB
        await self.update_console_status()
        
        client.has_synced = True
        
        # Check commands
        await client.check_and_sync_commands()

        # Start API Server
        await self.api_server.start()

        # Start Terminal Listener
        try:
            terminal_utils.start_terminal_listener(self.loop, self.handle_terminal_input)
        except Exception as e:
            logger.error(f"Failed to start terminal listener: {e}")

    async def on_raw_message_delete(self, payload):
        """
        Detects when a message is manually deleted by a user.
        If the deleted message is a Status Bar, we clean up its DB entry and Console listing.
        """
        try:
            # Ignore if this deletion was initiated by the bot (e.g. during a move/drop)
            if payload.message_id in self.pending_drops:
                self.pending_drops.discard(payload.message_id)
                return

            # Check if deleted message ID matches any active bar's message_id
            target_channel = None
            
            for cid, data in self.active_bars.items():
                bar_id = data.get("message_id")
                
                if payload.message_id == bar_id:
                    target_channel = cid
                    logger.info(f"🗑️ Status Bar manually deleted in channel {cid}")
                    break
            
            if target_channel:
                # Cleanup
                if target_channel in self.active_bars:
                    del self.active_bars[target_channel]
                
                memory_manager.delete_bar(target_channel)
                memory_manager.remove_bar_whitelist(target_channel)
                
                # Sync Console
                await self.update_console_status()

        except Exception as e:
            logger.error(f"Error in on_raw_message_delete: {e}")

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
                
                # SANITIZATION: Filter out invalid/test IDs (Discord Snowflakes are > 17 digits)
                # 1000000000000000 is roughly early 2015.
                if cid < 1000000000000000:
                     # logger.warning(f"⚠️ Ignoring invalid/test channel ID in whitelist: {cid}")
                     continue
                
                # We rely on active_bars (DB loaded) for the "link" info
                bar_data = self.active_bars.get(cid)
                
                status_emoji = default_emoji
                
                if bar_data:
                    # 1. Priority: Explicit DB Field
                    if bar_data.get('current_prefix'):
                         status_emoji = bar_data.get('current_prefix')
                    
                    # 2. Fallback: Derive from Content
                    elif bar_data.get('content'):
                         for emoji in ui.BAR_PREFIX_EMOJIS:
                             if bar_data['content'].strip().startswith(emoji):
                                 status_emoji = emoji
                                 break
                    
                    # 3. Stale Prefix Check: If status is default (NotWatching) but content starts with different emoji, use content
                    if status_emoji == default_emoji and bar_data.get('content'):
                         for emoji in ui.BAR_PREFIX_EMOJIS:
                             if bar_data['content'].strip().startswith(emoji):
                                 status_emoji = emoji
                                 break

                notification_mark = ""
                if bar_data and bar_data.get('has_notification'):
                     notification_mark = f" {config.NOTIFICATION_EMOJI}"

                if bar_data:
                    guild_id = bar_data.get('guild_id')
                    if not guild_id:
                        ch = self.get_channel(cid)
                        if ch: guild_id = ch.guild.id

                    target_id = bar_data.get('checkmark_message_id') or bar_data.get('message_id')
                    
                    if guild_id and target_id:
                        link = f"https://discord.com/channels/{guild_id}/{cid}/{target_id}"
                        log_lines.append(f"{status_emoji} {link}{notification_mark}")
                    else:
                        log_lines.append(f"{status_emoji} <#{cid}>{notification_mark}")
                else:
                    log_lines.append(f"{status_emoji} <#{cid}>")
            except:
                pass
                
        divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
        header = f"{divider}\n{ui.FLAVOR_TEXT['UPLINKS_HEADER']}\n"
        
        # Build Messages (Max 2000 chars each)
        messages_content = []
        
        current_msg_content = header
        is_first = True
        
        for line in log_lines:
            # +1 for newline
            if len(current_msg_content) + len(line) + 1 > 2000:
                messages_content.append(current_msg_content)
                current_msg_content = line
                is_first = False
            else:
                if is_first and current_msg_content == header:
                    current_msg_content += line
                elif not is_first and current_msg_content == line: # Start of new msg
                    pass # Already set
                else:
                    current_msg_content += "\n" + line
        
        if current_msg_content:
            messages_content.append(current_msg_content)
            
        if not messages_content:
             messages_content.append(header + "(No uplinks active)")

        # Update Messages
        channel = targets[0].channel
        new_msg_list = []
        
        for i, content in enumerate(messages_content):
            # Only last message gets the buttons
            view = ui.ConsoleControlView() if i == len(messages_content) - 1 else None
            
            if i < len(targets):
                msg = targets[i]
                try:
                    await services.service.limiter.wait_for_slot("edit_message", channel.id)
                    # Optimization: Don't edit if same
                    if msg.content != content: # View check hard, but content check easy
                        await msg.edit(content=content, view=view)
                    # Ensure view is correct even if content same (e.g. button state change)
                    if msg.content == content and i == len(messages_content) - 1:
                         await msg.edit(view=view)
                         
                    new_msg_list.append(msg)
                except discord.NotFound:
                    # Lost message -> Recreate
                    try:
                        m = await channel.send(content, view=view)
                        new_msg_list.append(m)
                    except: pass
                except discord.HTTPException as e:
                    # Network/Server Error (Transient) -> Keep Original, Don't Dupe
                    logger.warning(f"⚠️ HTTP Error editing console msg {msg.id}: {e}. Keeping original.")
                    new_msg_list.append(msg)
                except Exception as e:
                    logger.error(f"❌ Error editing console msg {msg.id}: {e}")
                    new_msg_list.append(msg)
            else:
                # New message
                try:
                    m = await channel.send(content, view=view)
                    new_msg_list.append(m)
                except: pass
        
        # Delete extras
        if len(targets) > len(messages_content):
            for i in range(len(messages_content), len(targets)):
                try: await targets[i].delete()
                except: pass

        self.console_progress_msgs = new_msg_list

    async def check_and_sync_commands(self):
        """Checks if commands have changed since last boot and syncs if needed."""
        current_hash = self.get_tree_hash()
        stored_hash = None
        
        logger.info("Checking command tree sync status...")
        
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
        await self.api_server.stop()
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
                self.active_bars.pop(channel.id, None)
                memory_manager.delete_bar(channel.id)
            return

        # 2. Fallback: Scan (only if not in DB)
        try:
            async for msg in channel.history(limit=20):
                if msg.id == exclude_msg_id: continue
                
                if msg.author.id == self.user.id:
                    is_target = False
                    
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                cid_str = getattr(child, "custom_id", "") or ""
                                if cid_str.startswith("bar_"):
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
            self.active_bars.pop(channel.id, None)
            memory_manager.delete_bar(channel.id)

            # 2. Scan and Delete
            async for msg in channel.history(limit=20):
                if msg.author.id == self.user.id:
                    is_target = False
                    
                    # Check Components (Buttons)
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                cid_str = getattr(child, "custom_id", "") or ""
                                if cid_str.startswith("bar_"):
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

    async def find_last_bar_message(self, channel):
        """Finds (message, content) from DB or scan. Returns (None, content) if DB-only."""
        # 1. DB (Check if valid)
        if channel.id in self.active_bars:
            content = self.active_bars[channel.id]["content"]
            if content is not None:
                # We store CLEAN content in DB now.
                return (None, content)
            # If content is None, fall through to scan (Corruption Recovery)
            
        # 2. Scan
        try:
            async for msg in channel.history(limit=20):
                if msg.author.id == self.user.id:
                    is_bar = False
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                cid_str = getattr(child, "custom_id", "") or ""
                                if cid_str.startswith("bar_"):
                                    is_bar = True
                                    break
                            if is_bar: break
                    
                    if not is_bar and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                is_bar = True
                                break
                
                    if is_bar:
                        return (msg, msg.content)
        except Exception as e:
            logger.warning(f"Find last bar failed: {e}")
        return (None, None)

    async def update_bar_prefix(self, interaction, new_prefix_emoji):
        """Updates the bar prefix. Edits in-place if bottom. Drops WITHOUT checkmark if moving."""
        
        # Defer immediately to prevent timeout (App didn't respond)
        try: await interaction.response.defer(ephemeral=True)
        except: pass

        # 1. Find existing content
        content = None
        found_msg, found_raw = await self.find_last_bar_message(interaction.channel)
        
        # Auto-Adopt if found via scan but missing in DB
        if found_msg and interaction.channel_id not in self.active_bars:
             await self.handle_bar_touch(interaction.channel_id, found_msg)
        
        if found_raw:
            # ANGEL GUARD: Ignore update if it is an Angel bar
            clean_found = found_raw.replace(' \n', '\n')
            if clean_found == ui.ANGEL_CONTENT or clean_found == ui.DARK_ANGEL_CONTENT:
                try: 
                    await interaction.followup.send("❌ Cannot update prefix on an Angel Bar.", ephemeral=True)
                    await asyncio.sleep(2.0)
                    await interaction.delete_original_response()
                except: pass
                return

            content = found_raw
            chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
            if chk in content:
                content = content.replace(chk, "").strip()
            
            content = content.strip().replace('\n', ' ')
            
            # SMART STRIP: Only remove the status prefix, preserving content emojis.
            stripped = False
            
            # 1. Try DB Prefix (Most accurate)
            if interaction.channel_id in self.active_bars:
                db_prefix = self.active_bars[interaction.channel_id].get("current_prefix")
                if db_prefix and content.startswith(db_prefix):
                    content = content[len(db_prefix):].strip()
                    stripped = True

            # 2. Try Known Prefixes (if not stripped yet)
            if not stripped:
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if content.startswith(emoji):
                        content = content[len(emoji):].strip()
                        stripped = True
                        break 
            
            # 3. Fallback Regex (Only ONCE, and only if we haven't found a valid prefix yet)
            # CAUTION: This might eat the first char of emoji-only content if it's not in the known list.
            # But it's needed for "stuck" prefixes not in the list.
            # To be safe, we only do this if we haven't found a known one.
            if not stripped:
                match = re.match(r'^(<a?:[^:]+:[0-9]+>)\s*', content)
                if match:
                    # Heuristic: Only strip if it looks like a "status" (usually followed by space or text)
                    # If the user has a bar of JUST emojis, the first one might be content.
                    # But status prefixes are also emojis.
                    # We'll assume if we are calling /thinking, the user WANTS to replace the first emoji if it looks like a prefix.
                    content = content[match.end():].strip()
                    stripped = True

        if not content:
            # If we stripped everything (empty bar), or it was empty to begin with, we allow it.
            # The final content will just be the prefix.
            content = ""

        content_with_prefix = f"{new_prefix_emoji} {content.strip()}"
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
            full_content = f"{content_with_prefix}{chk}"
            full_content = re.sub(r'>[ \t]+<', '><', full_content)

            try:
                await services.service.limiter.wait_for_slot("edit_message", interaction.channel_id)
                await active_msg.edit(content=full_content)
                
                self.active_bars[interaction.channel_id]["content"] = content_with_prefix
                self.active_bars[interaction.channel_id]["checkmark_message_id"] = active_msg.id 
                self.active_bars[interaction.channel_id]["current_prefix"] = new_prefix_emoji
                self.active_bars[interaction.channel_id]["has_notification"] = False
                
                memory_manager.save_bar(
                    interaction.channel_id, 
                    interaction.guild_id,
                    active_msg.id,
                    interaction.user.id,
                    content_with_prefix,
                    persisting,
                    current_prefix=new_prefix_emoji,
                    has_notification=False,
                    checkmark_message_id=active_msg.id
                )
                
                # Success - Delete original ephemeral response
                try: 
                    await asyncio.sleep(0.5)
                    await interaction.delete_original_response() 
                except: pass
                
                # Sync Console (Touch Event)
                await self.handle_bar_touch(interaction.channel_id)
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
            "current_prefix": new_prefix_emoji,
            "has_notification": False
        }
        self._register_bar_message(interaction.channel_id, msg.id, view)
        
        memory_manager.save_bar(
            interaction.channel_id, 
            interaction.guild_id,
            msg.id,
            interaction.user.id,
            content_with_prefix,
            persisting,
            current_prefix=new_prefix_emoji,
            has_notification=False,
            checkmark_message_id=new_check_id
        )
        
        # Sync Console (Touch Event)
        await self.handle_bar_touch(interaction.channel_id)
        
        try: 
            await asyncio.sleep(0.5)
            await interaction.delete_original_response()
        except: pass

    async def replace_bar_content(self, interaction, new_content):
        """Replaces the entire bar content (preserving checkmark) and drops it."""
        # Cleanup old
        await self.cleanup_old_bars(interaction.channel)
        
        # Special Handling for Angel/Dark Angel to preserve newline layout
        if new_content == ui.ANGEL_CONTENT or new_content == ui.DARK_ANGEL_CONTENT:
             new_content = new_content.strip()
        else:
             new_content = new_content.strip().replace('\n', ' ')
             # Strip spaces between emojis
             new_content = re.sub(r'>[ \t]+<', '><', new_content)
        
        # Send new
        full_content = new_content
        
        # Preserve persistence
        persisting = False
        if interaction.channel_id in self.active_bars:
            persisting = self.active_bars[interaction.channel_id].get("persisting", False)
        
        # Ensure view is attached
        view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, persisting)
        
        await interaction.response.defer(ephemeral=True)
        
        await services.service.limiter.wait_for_slot("send_message", interaction.channel_id)
        msg = await interaction.channel.send(full_content, view=view)
        
        self.active_bars[interaction.channel_id] = {
            "content": full_content,
            "user_id": interaction.user.id,
            "message_id": msg.id,
            "checkmark_message_id": msg.id,
            "persisting": persisting,
            "has_notification": False
        }
        self._register_bar_message(interaction.channel_id, msg.id, view)
        
        # Sync to DB
        memory_manager.save_bar(
            interaction.channel_id, 
            interaction.guild_id,
            msg.id,
            interaction.user.id,
            full_content,
            persisting,
            has_notification=False,
            checkmark_message_id=msg.id
        )
        
        # Touch Event
        await self.handle_bar_touch(interaction.channel_id)
        
        await interaction.edit_original_response(content="✅")
        await asyncio.sleep(0.5)
        await interaction.delete_original_response()

    async def sync_bars(self):
        """
        Checks all whitelisted bars for existence. Removes invalid entries from DB/Memory.
        Returns the number of removed/invalid bars.
        """
        bar_whitelist = memory_manager.get_bar_whitelist()
        removed_count = 0
        
        # Copy list to avoid modification during iteration issues
        for cid_str in list(bar_whitelist):
            cid = int(cid_str)
            
            # 1. Check if known in DB active_bars
            if cid not in self.active_bars:
                # In whitelist but no active bar data -> Remove
                memory_manager.remove_bar_whitelist(cid)
                removed_count += 1
                continue
                
            # 2. Check Server Existence
            bar_data = self.active_bars[cid]
            msg_id = bar_data.get("message_id")
            
            if not msg_id:
                 # Corrupt data -> Remove
                 del self.active_bars[cid]
                 memory_manager.delete_bar(cid)
                 memory_manager.remove_bar_whitelist(cid)
                 removed_count += 1
                 continue
                 
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                await ch.fetch_message(msg_id)
                # If succeeds, it exists. Do nothing.
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                # Missing -> Remove
                if cid in self.active_bars: del self.active_bars[cid]
                memory_manager.delete_bar(cid)
                memory_manager.remove_bar_whitelist(cid)
                removed_count += 1

        # Update Console
        await self.update_console_status()
        return removed_count

    async def set_reboot_mode(self):
        """
        Sets all active bars to 'Rebooting' mode visually.
        Updates DB so Console reflects the reboot status. 
        Saves original prefix for restoration (via previous_state).
        Removes interactive views (buttons) during reboot.
        """
        logger.info("🔄 Setting system to Reboot Mode...")
        reboot_emoji = ui.FLAVOR_TEXT['REBOOT_EMOJI']
        
        tasks = []
        
        async def update_bar(cid, bar_data):
            try:
                msg_id = bar_data.get("message_id")
                if not msg_id: return
                
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return
                
                msg = await ch.fetch_message(msg_id)
                
                # Determine current content without prefix
                current_content = bar_data.get("content", "")
                
                # Strip Checkmark first (just in case it's in DB content)
                chk_emoji = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                if chk_emoji in current_content:
                    current_content = current_content.replace(chk_emoji, "").strip()
                
                # Determine REAL Prefix (to save)
                real_prefix = bar_data.get("current_prefix")
                
                # Strip existing prefix from content
                stripped = False
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if current_content.startswith(emoji):
                        current_content = current_content[len(emoji):].strip()
                        if not real_prefix: real_prefix = emoji
                        stripped = True
                        break
                
                # Fallback Regex Strip (for unknown emojis)
                if not stripped:
                    match = re.match(r'^(<a?:[^:]+:[0-9]+>)\s*', current_content)
                    if match:
                        current_content = current_content[match.end():].strip()
                        if not real_prefix: real_prefix = match.group(1)

                if not real_prefix: 
                    real_prefix = "<a:NotWatching:1301840196966285322>" # Default if lost

                # Construct Reboot Content
                new_content = f"{reboot_emoji} {current_content}"
                new_content = re.sub(r'>[ \t]+<', '><', new_content)
                
                # Handle Checkmark
                check_id = bar_data.get("checkmark_message_id")
                has_merged_check = (check_id == msg_id)
                
                if has_merged_check:
                    if chk_emoji not in new_content:
                        new_content = f"{new_content} {chk_emoji}"
                        new_content = re.sub(r'>[ \t]+<', '><', new_content)
                
                # Edit Message (With Reboot View)
                view = ui.RebootView()
                await services.service.limiter.wait_for_slot("edit_message", cid)
                await msg.edit(content=new_content, view=view)

                # Save Original Prefix to Previous State (Safe JSON blob)
                # We grab existing previous_state if any? No, we just overwrite for this cycle.
                memory_manager.save_previous_state(cid, {'original_prefix': real_prefix})

                # Update DB so Console Matches
                memory_manager.save_bar(
                    cid, 
                    bar_data.get("guild_id"),
                    msg_id,
                    bar_data["user_id"],
                    new_content,
                    bar_data.get("persisting", False),
                    current_prefix=reboot_emoji,
                    has_notification=False,
                    checkmark_message_id=check_id
                )
                
            except Exception as e:
                logger.warning(f"Failed to set reboot mode for {cid}: {e}")

        for cid, bar_data in list(self.active_bars.items()):
            tasks.append(update_bar(cid, bar_data))
            
        if tasks:
            await asyncio.gather(*tasks)
        
        # Trigger Console Update
        await self.update_console_status()

    async def set_shutdown_mode(self):
        """
        Sets all active bars to 'Shutdown' mode visually.
        Updates DB so Console reflects status.
        Saves original prefix for restoration (via previous_state).
        Removes interactive views (buttons) during shutdown.
        """
        logger.info("🛑 Setting system to Shutdown Mode...")
        shutdown_emoji = ui.FLAVOR_TEXT['SHUTDOWN_EMOJI']
        
        tasks = []
        
        async def update_bar(cid, bar_data):
            try:
                msg_id = bar_data.get("message_id")
                if not msg_id: return
                
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                if not ch: return
                
                msg = await ch.fetch_message(msg_id)
                
                # Determine current content without prefix
                current_content = bar_data.get("content", "")
                
                # Strip Checkmark first
                chk_emoji = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                if chk_emoji in current_content:
                    current_content = current_content.replace(chk_emoji, "").strip()
                
                # Determine REAL Prefix (to save)
                real_prefix = bar_data.get("current_prefix")

                # Strip existing prefix
                stripped = False
                for emoji in ui.BAR_PREFIX_EMOJIS:
                    if current_content.startswith(emoji):
                        current_content = current_content[len(emoji):].strip()
                        if not real_prefix: real_prefix = emoji
                        stripped = True
                        break
                
                # Fallback Regex Strip
                if not stripped:
                    match = re.match(r'^(<a?:[^:]+:[0-9]+>)\s*', current_content)
                    if match:
                        current_content = current_content[match.end():].strip()
                        if not real_prefix: real_prefix = match.group(1)

                if not real_prefix: 
                    real_prefix = "<a:NotWatching:1301840196966285322>"

                # Construct Shutdown Content
                new_content = f"{shutdown_emoji} {current_content}"
                new_content = re.sub(r'>[ \t]+<', '><', new_content)
                
                # Handle Checkmark
                check_id = bar_data.get("checkmark_message_id")
                has_merged_check = (check_id == msg_id)
                
                if has_merged_check:
                    if chk_emoji not in new_content:
                        new_content = f"{new_content} {chk_emoji}"
                        new_content = re.sub(r'>[ \t]+<', '><', new_content)
                
                # Edit Message (With Shutdown View)
                view = ui.ShutdownView()
                await services.service.limiter.wait_for_slot("edit_message", cid)
                await msg.edit(content=new_content, view=view)

                # Save Original Prefix to Previous State
                memory_manager.save_previous_state(cid, {'original_prefix': real_prefix})

                # Update DB
                memory_manager.save_bar(
                    cid, 
                    bar_data.get("guild_id"),
                    msg_id,
                    bar_data["user_id"],
                    new_content,
                    bar_data.get("persisting", False),
                    current_prefix=shutdown_emoji,
                    has_notification=False,
                    checkmark_message_id=check_id
                )
                
            except Exception as e:
                logger.warning(f"Failed to set shutdown mode for {cid}: {e}")

        for cid, bar_data in list(self.active_bars.items()):
            tasks.append(update_bar(cid, bar_data))
            
        if tasks:
            await asyncio.gather(*tasks)
        
        # Trigger Console Update
        await self.update_console_status()

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
                divider = ui.FLAVOR_TEXT["COSMETIC_DIVIDER"]
                
                # 1. Powering Down (Update Header Subtitle)
                power_down_sub = "-# Powering Down . . ."
                full_header = f"{header_text}\n{power_down_sub}\n{divider}"
                
                await services.service.limiter.wait_for_slot("edit_message", h_msg.channel.id)
                await h_msg.edit(content=full_header)
                
                await asyncio.sleep(5.0) 
                
                # 2. Final Status: System Offline (Update Header Subtitle)
                offline_sub = ui.FLAVOR_TEXT["SYSTEM_OFFLINE"]
                final_header = f"{header_text}\n{offline_sub}\n{divider}"
                
                await services.service.limiter.wait_for_slot("edit_message", h_msg.channel.id)
                await h_msg.edit(content=final_header)
                
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
            # Set visuals to Reboot Mode (Preserves DB state)
            await self.set_reboot_mode()

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
            except Exception as e:
                logger.error(f"Failed to write restart meta: {e}")
        else:
            # Set visuals to Shutdown Mode
            await self.set_shutdown_mode()
            
            try:
                with open(config.SHUTDOWN_FLAG_FILE, "w") as f: f.write("shutdown")
            except Exception as e:
                logger.error(f"Failed to write shutdown flag: {e}")

        # 6. Close & Exit
        await self.close()
        
        if restart:
            # Wait for Discord to fully release the session/token
            logger.info("⏳ Session closed. Waiting 5s for token release before restart...")
            await asyncio.sleep(5.0)
            
            # Exit process is handled in main block after client.run returns
        else:
            # Exit process is handled in main block after client.run returns
            pass

# --- Helper Class for Internal Interaction Mocking ---
class MockInteraction:
    def __init__(self, client, channel, user, message):
        self.client = client
        self.channel = channel
        self.channel_id = channel.id
        self.user = user
        self.message = message
        self.guild = channel.guild if hasattr(channel, 'guild') else None
        self.guild_id = channel.guild.id if hasattr(channel, 'guild') and channel.guild else None
        self.response = self.MockResponse(self)
        self.followup = self.response # Alias for followup.send
    
    async def delete_original_response(self): pass
    async def edit_original_response(self, content=None, view=None, **kwargs): pass 

    class MockResponse:
        def __init__(self, parent):
            self.parent = parent
            self.last_message = None
            
        async def send_message(self, content=None, ephemeral=False, delete_after=None, embed=None, **kwargs):
            # Prefix Command Handling:
            # 1. If content is "✅", react with Checkmark.
            # 2. If content starts with "❌" or "⚠️", react with X (Cross).
            # 3. If ephemeral=False (Help, Goodbot, Testmessage), send as public message.
            # 4. If ephemeral=True but not a status check (e.g. Console), send with delete_after?
            
            # Reaction Mapping
            if content == "✅":
                try: await self.parent.message.add_reaction(ui.FLAVOR_TEXT.get("CUSTOM_CHECKMARK", "✅"))
                except: pass
                return

            if content == "<a:SeraphHyperNo:1331531123851006025>":
                try: await self.parent.message.add_reaction("<a:SeraphHyperNo:1331531123851006025>")
                except: pass
                return

            if content and (content.startswith("❌") or content.startswith("⚠️")):
                try: await self.parent.message.add_reaction("<a:SeraphHyperNo:1331531123851006025>") # Custom X
                except: 
                    try: await self.parent.message.add_reaction("❌")
                    except: pass
                return

            # Text Output (Only if not effectively hidden/status)
            # For "console", we want it to appear for 3s then delete.
            # For "help"/"goodbot", we want it to persist.
            
            if not ephemeral or delete_after or kwargs.get('view'):
                try:
                    msg = await self.parent.channel.send(content=content, embed=embed, delete_after=delete_after, **kwargs)
                    self.last_message = msg
                except Exception as e:
                    logger.error(f"MockInteraction send failed: {e}")
        
        # Alias for followup.send
        async def send(self, content=None, **kwargs):
            await self.send_message(content, **kwargs)

        async def defer(self, ephemeral=False): pass
        
        def is_done(self): return False
        
        async def delete_original_response(self): pass
        
        async def edit_original_response(self, content=None, view=None, **kwargs):
            # Proxy to send_message to handle reactions if content is a status symbol
            if content:
                await self.send_message(content=content, **kwargs)
    
    async def original_response(self):
        if self.response.last_message:
            return self.response.last_message
        return None

client = LMStudioBot()

# ==========================================
# SLASH COMMANDS
# ==========================================



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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
    else:
        memory_manager.add_allowed_channel(interaction.channel_id)
        await client.update_console_status()
        await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
        
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        memory_manager.remove_allowed_channel(interaction.channel_id)
        await client.update_console_status()
        await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)
    else:
        await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)

@client.tree.command(name="enableall", description="Enable Global Chat Mode (Talk in ALL channels).")
async def enableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.set_server_setting("global_chat_enabled", True)
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

@client.tree.command(name="disableall", description="Disable Global Chat Mode (Talk in whitelist only).")
async def disableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.set_server_setting("global_chat_enabled", False)
    await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)

@client.tree.command(name="reboot", description="Full restart of the bot process.")
async def reboot_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    # Construct Console Link
    guild_id = interaction.guild_id if interaction.guild else "@me"
    target_ch = config.STARTUP_CHANNEL_ID
    msg_id = client.startup_header_msg.id if hasattr(client, 'startup_header_msg') and client.startup_header_msg else None
    
    url = f"https://discord.com/channels/{guild_id}/{target_ch}"
    if msg_id: url += f"/{msg_id}"
    
    if not target_ch: url = "https://discord.com/channels/@me" # Fallback

    await interaction.response.send_message(f"[Jump to Console]({url})", ephemeral=True, delete_after=2.0)
    await client.perform_shutdown_sequence(interaction, restart=True)

@client.tree.command(name="console", description="Get a link to the console channel.")
async def console_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    # Construct Console Link
    guild_id = interaction.guild_id if interaction.guild else "@me"
    target_ch = config.STARTUP_CHANNEL_ID
    msg_id = client.startup_header_msg.id if hasattr(client, 'startup_header_msg') and client.startup_header_msg else None
    
    url = f"https://discord.com/channels/{guild_id}/{target_ch}"
    if msg_id: url += f"/{msg_id}"
    
    if not target_ch: url = "https://discord.com/channels/@me"

    await interaction.response.send_message(f"[Jump to Console]({url})", ephemeral=True, delete_after=3.0)

@client.tree.command(name="shutdown", description="Gracefully shut down the bot.")
async def shutdown_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    # Shutdown sequence triggers UI changes, so we give a brief checkmark before it takes over/closes
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
    await client.perform_shutdown_sequence(interaction, restart=False)

@client.tree.command(name="killmyembeds", description="Toggle auto-suppression of hyperlink embeds for your messages.")
async def killmyembeds_command(interaction: discord.Interaction):
    is_suppressed = memory_manager.toggle_suppressed_user(interaction.user.id)
    if is_suppressed:
        await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
    else:
        await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)

@client.tree.command(name="suppressembedson", description="Enable the server-wide embed suppression feature.")
async def suppressembedson_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.set_server_setting("embed_suppression", True)
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

@client.tree.command(name="suppressembedsoff", description="Disable the server-wide embed suppression feature.")
async def suppressembedsoff_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.set_server_setting("embed_suppression", False)
    await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)

@client.tree.command(name="clearmemory", description="Clear the bot's memory for this channel.")
async def clearmemory_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    # Update cutoff time to NOW
    client._update_lru_cache(client.channel_cutoff_times, interaction.channel_id, interaction.created_at, limit=500)
    
    memory_manager.clear_channel_memory(interaction.channel_id, interaction.channel.name)
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

@client.tree.command(name="bugreport", description="Submit a bug report.")
async def bugreport_command(interaction: discord.Interaction):
    view = ui.BugReportButtonView()
    await interaction.response.send_message("Click below to submit a report:", view=view, ephemeral=True)

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

@client.tree.command(name="cleargoodbots", description="Clear the Good Bot leaderboard (Admin Only).")
async def cleargoodbots_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    if memory_manager.clear_good_bot_leaderboard():
        await interaction.response.send_message("✅ Good Bot leaderboard has been wiped.", ephemeral=True, delete_after=3.0)
    else:
        await interaction.response.send_message("❌ Failed to wipe Good Bot leaderboard.", ephemeral=True, delete_after=3.0)

@client.tree.command(name="synccommands", description="Force sync slash commands.")
async def synccommands_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
    try:
        await client.tree.sync()
        # Update hash
        new_hash = client.get_tree_hash()
        with open(config.COMMAND_STATE_FILE, "w") as f:
            f.write(new_hash)
    except Exception as e:
        logger.error(f"Sync failed: {e}")

@client.tree.command(name="debug", description="Toggle Debug Mode (Admin Only).")
async def debug_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    current = memory_manager.get_server_setting("debug_mode", False)
    new_mode = not current
    memory_manager.set_server_setting("debug_mode", new_mode)
    
    if new_mode:
        await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
    else:
        await interaction.response.send_message("<a:SeraphHyperNo:1331531123851006025>", ephemeral=True, delete_after=0.5)

@client.tree.command(name="testmessage", description="Send a test message (Admin/Debug Only).")
async def testmessage_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=False)
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
    await interaction.followup.send(response, view=view, ephemeral=False)

@client.tree.command(name="clearallmemory", description="Wipe ALL chat memories (Admin/Debug Only).")
async def clearallmemory_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.wipe_all_memories()
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

@client.tree.command(name="wipelogs", description="Wipe ALL logs (Admin/Debug Only).")
async def wipelogs_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    memory_manager.wipe_all_logs()
    await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)

@client.tree.command(name="debugtest", description="Run unit tests and report results (Admin Only).")
async def debugtest_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    # 1. Send Thinking Emoji
    await interaction.response.send_message("<a:Thinking:1322962569300017214>", ephemeral=True)
    
    import io
    
    start_time = time.time()
    
    # Run pytest in a subprocess to ensure isolation and prevent memory pollution
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", "-v", "--color=no", "tests/",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    output = stdout.decode() + stderr.decode()
    exit_code = process.returncode
    
    duration = time.time() - start_time
    
    logger.info(f"Debug Test Output:\n{output}")
    
    # 2. Determine Result Emoji
    result_emoji = "✅" if exit_code == 0 else "<a:SeraphCryHandsSnap:1297004800117837906>"
    
    msg = f"{result_emoji} **Unit Test Results** ({duration:.3f}s)"
    file = discord.File(io.BytesIO(output.encode()), filename="test_results.txt")
    
    # 3. Edit Original Message
    await interaction.edit_original_response(content=msg, attachments=[file])

@client.tree.command(name="nukedatabase", description="NUCLEAR: Wipes the entire database and reboots. (Admin Only)")
async def nukedatabase_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    # Confirmation dialog could be nice, but user asked for the command.
    # We'll just do it but defer first as it might take a moment.
    await interaction.response.defer(ephemeral=True)
    
    logger.warning(f"☢️ DATABASE NUKE INITIATED BY {interaction.user} ({interaction.user.id})")
    
    success = memory_manager.nuke_database()
    
    if success:
        await interaction.followup.send("☢️ **DATABASE NUKED.** All data has been erased. Rebooting system...", ephemeral=True)
        # Trigger reboot
        await client.perform_shutdown_sequence(interaction, restart=True)
    else:
        await interaction.followup.send("❌ Database nuke failed. Check logs.", ephemeral=True)

@client.tree.command(name="backup", description="Run a backup for the specified target (Temple, WM, or Shrine).")
@app_commands.describe(target="Target: 'temple', 'wm', or 'shrine'", upload_only="Skip download/export and only archive/upload existing files.")
async def backup_command(interaction: discord.Interaction, target: str, upload_only: bool = False):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    target = target.lower()
    target_id = None
    output_name = None
    target_type = "guild"
    
    if target == "temple":
        target_id = config.TEMPLE_GUILD_ID
        output_name = "Temple"
    elif target == "wm":
        target_id = config.WM_GUILD_ID
        output_name = "WM"
    elif target == "shrine":
        target_id = config.SHRINE_CHANNEL_ID
        output_name = "Shrine"
        target_type = "channel"
    else:
         await interaction.response.send_message("⚠️ Unknown target. Use `temple`, `wm`, or `shrine`.", ephemeral=True)
         return
         
    if not target_id:
         await interaction.response.send_message(f"❌ ID for {output_name} is not configured.", ephemeral=True)
         return

    # Estimate Total Channels
    estimated_total = 0
    if target_type == "guild" and not upload_only:
        try:
            guild = client.get_guild(target_id)
            if not guild:
                guild = await client.fetch_guild(target_id)
            if guild:
                 channels = await guild.fetch_channels()
                 estimated_total = len(channels)
        except Exception as e:
             logger.warning(f"Failed to fetch estimated channel count: {e}")
    else:
        estimated_total = 1

    await interaction.response.send_message(f"🚀 Initializing backup for **{output_name}** ({target_type.capitalize()})...", ephemeral=False)
    progress_msg = await interaction.original_response()
    
    # Create Cancel Event & View
    cancel_event = asyncio.Event()
    view = ui.BackupControlView(cancel_event)
    
    # Use a mutable container for the message so callback can update it if token expires
    msg_container = {"msg": progress_msg}

    try:
        await progress_msg.edit(view=view)
    except: pass
    
    async def progress_callback(pct, status):
        try:
            bar = helpers.generate_progress_bar(pct)
            # Update view as well to keep button active? No, view persists.
            await msg_container["msg"].edit(content=f"**{output_name} Backup**\n{bar} {pct}%\n{status}", view=view)
        except discord.HTTPException as e:
            if e.code == 50027: # Invalid Webhook Token (Expired)
                 logger.warning("Backup interaction token expired. Sending new status message.")
                 try:
                     new_msg = await interaction.channel.send(content=f"**{output_name} Backup (Continued)**\n{bar} {pct}%\n{status}", view=view)
                     msg_container["msg"] = new_msg # Update reference
                 except Exception as ex:
                     logger.error(f"Failed to send fallback status message: {ex}")
            else:
                 pass # Other error
        except Exception: pass
        
    success, result = await backup_manager.run_backup(
        target_id, 
        output_name, 
        target_type=target_type, 
        progress_callback=progress_callback, 
        estimated_total_channels=estimated_total,
        cancel_event=cancel_event,
        skip_download=upload_only
    )
    
    # Remove View on Finish
    try:
        if success:
             await msg_container["msg"].edit(content=result, view=None)
        else:
             await msg_container["msg"].edit(content=f"❌ **Backup Failed:** {result}", view=None)
    except discord.HTTPException as e:
        if e.code == 50027:
             # Expired at the very end
             if success:
                  await interaction.channel.send(content=result)
             else:
                  await interaction.channel.send(content=f"❌ **Backup Failed:** {result}")
        else:
            pass



@client.tree.command(name="bar", description="Drop the bar (leaves checkmark behind).")
async def bar_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar.", ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=True)
    await client.drop_status_bar(interaction.channel_id, move_bar=True, move_check=False)
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="dropall", description="Drop the bar AND the checkmark together.")
async def dropall_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar.", ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=True)
    await client.drop_status_bar(interaction.channel_id, move_bar=True, move_check=True)
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="scanemojis", description="Extract custom emojis from recent messages into a JSON database.")
@app_commands.describe(limit="Number of messages to scan (Default: 20)")
async def scanemojis_command(interaction: discord.Interaction, limit: int = 20):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    await interaction.response.defer(ephemeral=True)
    
    emoji_pattern = re.compile(r'<(a?):(\w+):(\d+)>')
    found_emojis = {}
    
    count = 0
    try:
        async for message in interaction.channel.history(limit=limit):
            # Find all matches in message content
            matches = emoji_pattern.findall(message.content)
            for animated, name, id in matches:
                # Reconstruct valid discord string
                # animated is 'a' or empty
                full_str = f"<{animated}:{name}:{id}>"
                found_emojis[name] = full_str
                count += 1
    except Exception as e:
        await interaction.followup.send(f"❌ Scan failed: {e}")
        return

    if not found_emojis:
        await interaction.followup.send("No custom emojis found in recent messages.")
        return

    # Create JSON file
    import io
    json_data = json.dumps(found_emojis, indent=4)
    file = discord.File(io.BytesIO(json_data.encode()), filename="emoji_db.json")
    
    await interaction.followup.send(f"✅ Scanned {limit} messages. Found {len(found_emojis)} unique emojis (from {count} total instances).", file=file)

@client.tree.command(name="addbar", description="Summon a status bar to this channel.")
async def addbar_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    await interaction.response.defer(ephemeral=True)
    
    # 1. Scan and Delete Existing Bar (Limit 20)
    try:
        deleted = False
        async for msg in interaction.channel.history(limit=20):
            if msg.author.id == client.user.id:
                # Check if it looks like a bar
                is_bar = False
                if msg.components:
                    for row in msg.components:
                        for child in row.children:
                            if getattr(child, "custom_id", "").startswith("bar_"):
                                is_bar = True; break
                        if is_bar: break
                
                if not is_bar and msg.content:
                    for emoji in ui.BAR_PREFIX_EMOJIS:
                        if msg.content.strip().startswith(emoji):
                            is_bar = True; break
                
                if is_bar:
                    await msg.delete()
                    deleted = True
    except Exception as e:
        logger.warning(f"Addbar scan failed: {e}")

    # 2. Determine Content (Prefix)
    # Check DB for last known state
    db_bar = memory_manager.get_bar(interaction.channel_id)
    
    prefix = "<a:NotWatching:1301840196966285322>" # Default Speed 0
    if db_bar and db_bar.get('current_prefix'):
        prefix = db_bar.get('current_prefix')
    elif db_bar and db_bar.get('content'):
        # Try to extract from content if current_prefix column is empty
        for emoji in ui.BAR_PREFIX_EMOJIS:
            if db_bar['content'].startswith(emoji):
                prefix = emoji
                break

    # 3. Build Content
    master_content = memory_manager.get_master_bar() or "NyxOS Uplink Active"
    master_content = master_content.strip().replace('\n', ' ')
    
    content = f"{prefix} {master_content} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
    content = re.sub(r'>[ \t]+<', '><', content)
    
    # 4. Send
    # Preserve persistence if known
    persisting = db_bar.get('persisting', False) if db_bar else False
    
    view = ui.StatusBarView(content, interaction.user.id, interaction.channel_id, persisting)
    await services.service.limiter.wait_for_slot("send_message", interaction.channel_id)
    msg = await interaction.channel.send(content, view=view)
    
    # 5. Save to DB
    memory_manager.add_bar_whitelist(interaction.channel_id)
    
    client.active_bars[interaction.channel_id] = {
        "content": f"{prefix} {master_content}",
        "user_id": interaction.user.id,
        "message_id": msg.id,
        "checkmark_message_id": msg.id,
        "persisting": persisting,
        "current_prefix": prefix,
        "has_notification": False
    }
    client._register_bar_message(interaction.channel_id, msg.id, view)
    
    memory_manager.save_bar(
        interaction.channel_id, 
        interaction.guild_id,
        msg.id,
        interaction.user.id,
        f"{prefix} {master_content}",
        persisting,
        current_prefix=prefix,
        has_notification=False,
        checkmark_message_id=msg.id
    )
    
    # 6. Touch Event (Sync Console)
    await client.handle_bar_touch(interaction.channel_id)
    
    # Confirmation
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="removebar", description="Remove bar and un-whitelist channel.")
async def removebar_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return

    await interaction.response.defer(ephemeral=True)
    memory_manager.remove_bar_whitelist(interaction.channel_id)
    await client.wipe_channel_bars(interaction.channel)
    
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="cleanbars", description="Wipe all Uplink Bar artifacts and checkmarks from the channel.")
async def cleanbars_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.wipe_channel_bars(interaction.channel)
    
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="idle", description="Set all bars to Idle (Not Watching).")
async def idle_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=True)
    count = await client.idle_all_bars()
    
    await interaction.edit_original_response(content="✅")
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="dropcheck", description="Drop the checkmark onto the bar (drags bar down if needed).")
async def dropcheck_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
         await interaction.response.send_message("❌ No active bar.", ephemeral=True, delete_after=2.0)
         return
    
    await interaction.response.defer(ephemeral=True)
    # User: "dragging it all the way down to the bottom". So move_bar=True.
    await client.drop_status_bar(interaction.channel_id, move_bar=True, move_check=True)
    await interaction.edit_original_response(content="✅")
    await asyncio.sleep(0.5)
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
    await client.update_bar_prefix(interaction, "<a:Typing:1223747307657232405>")

@client.tree.command(name="brb", description="Set status to BRB.")
async def brb_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:SeraphBRB:1445618635719577671>")

@client.tree.command(name="processing", description="Set status to Processing.")
async def processing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Processing:1223643308140793969>")

@client.tree.command(name="angel", description="Set status to Angel.")
async def angel_command(interaction: discord.Interaction):
    await client.replace_bar_content(interaction, ui.ANGEL_CONTENT)

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



@client.tree.command(name="drop", description="Drop (refresh) the current Uplink Bar.")
async def drop_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar in this channel. Use `/bar` to create one.", ephemeral=True, delete_after=2.0)
        return
    
    await interaction.response.defer(ephemeral=True)
    # Default drop behavior: Drop All
    await client.drop_status_bar(interaction.channel_id, move_bar=True, move_check=True)
    await interaction.edit_original_response(content="✅")
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="help", description="Show the help index.")
async def help_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    embed = discord.Embed(title="NyxOS Help Index", color=discord.Color.blue())
    
    embed.add_field(
        name="General Commands", 
        value="`/help` - Show this help index.\n`/reportbug` - Submit a bug report.\n`/goodbot` - Show the Good Bot leaderboard.\n`/killmyembeds` - Toggle auto-suppression of link embeds.", 
        inline=False
    )
    
    embed.add_field(
        name="Bar Management", 
        value="`/bar` - Drop/Refresh bar (Checkmark stays behind).\n`/dropall` - Drop Bar + Checkmark.\n`/addbar` - Summon a persistent bar here.\n`/removebar` - Remove bar and un-whitelist channel.\n`/dropcheck` - Drop only the checkmark.\n`/cleanbars` - Wipe bar artifacts.", 
        inline=False
    )
    
    embed.add_field(
        name="Status Control (Global)", 
        value="`/global` - Update text on ALL bars.\n`/idle` - Set all bars to Idle (Not Watching).", 
        inline=False
    )
    
    embed.add_field(
        name="Status Control (Local)", 
        value="`/speed0` - Not Watching.\n`/speed1` - Watching Occasionally.\n`/speed2` - Watching Closely.\n`/thinking`, `/reading`, `/backlogging`, `/typing`\n`/brb`, `/processing`, `/pausing`\n`/angel`, `/darkangel`", 
        inline=False
    )
    
    embed.add_field(
        name="System / Admin", 
        value="`/console` - Jump to Console.\n`/addchannel` - Whitelist current channel.\n`/removechannel` - Blacklist current channel.\n`/enableall` - Enable Global Chat (All Channels).\n`/disableall` - Disable Global Chat (Whitelist Only).\n`/reboot` - Restart bot.\n`/shutdown` - Shutdown bot.\n`/clearmemory` - Clear channel memory.\n`/cleargoodbots` - Wipe Good Bot leaderboard.\n`/clearallmemory` - Wipe ALL memories.\n`/wipelogs` - Wipe ALL logs.\n`/debug` - Toggle Debug Mode.\n`/testmessage` - Send test message.\n`/synccommands` - Force sync slash commands.\n`/suppressembedson/off` - Global embed suppression.", 
        inline=False
    )
    
    await interaction.followup.send(embed=embed)

@client.tree.command(name="d", description="Alias for /drop")
async def d_command(interaction: discord.Interaction):
    await drop_command.callback(interaction)

@client.tree.command(name="c", description="Alias for /dropcheck")
async def c_command(interaction: discord.Interaction):
    await dropcheck_command.callback(interaction)

@client.tree.command(name="b", description="Alias for /bar")
async def b_command(interaction: discord.Interaction):
    await bar_command.callback(interaction)

@client.tree.command(name="global", description="Update text on all active bars.")
async def global_command(interaction: discord.Interaction, text: str):
    if not helpers.is_authorized(interaction.user):
         await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True, delete_after=2.0)
         return
    await interaction.response.defer(ephemeral=True)
    count = await client.global_update_bars(text)
    
    await interaction.edit_original_response(content="✅")
    await asyncio.sleep(0.5)
    await interaction.delete_original_response()

@client.tree.command(name="darkangel", description="Set status to Dark Angel.")
async def darkangel_command(interaction: discord.Interaction):
    await client.replace_bar_content(interaction, ui.DARK_ANGEL_CONTENT)

@client.tree.command(name="debugscan", description="Diagnose why the bot can't see the status bar (Admin).")
async def debugscan_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    log = []
    log.append(f"--- DEBUG SCAN FOR #{interaction.channel.name} ({interaction.channel_id}) ---")
    log.append(f"Bot ID: {client.user.id}")
    log.append(f"Active Bars Entry: {client.active_bars.get(interaction.channel_id)}")
    log.append(f"Allowed Channels: {memory_manager.get_allowed_channels()}")
    log.append("-" * 40)

    found_any = False
    count = 0
    
    try:
        async for msg in interaction.channel.history(limit=20):
            count += 1
            log.append(f"\n[MSG {msg.id}] Author: {msg.author.id} ({msg.author.name})")
            log.append(f"Content: {repr(msg.content)}")
            
            if msg.author.id != client.user.id:
                log.append("Result: IGNORED (Not me)")
                continue

            # Check 1: Buttons
            has_bar_btn = False
            btn_ids = []
            if msg.components:
                for row in msg.components:
                    for child in row.children:
                        cid = getattr(child, "custom_id", "") or "None"
                        btn_ids.append(cid)
                        if cid and cid.startswith("bar_"):
                            has_bar_btn = True
            
            log.append(f"Buttons: {btn_ids}")
            
            # Check 2: Prefix
            has_prefix = False
            matched_prefix = None
            for emoji in ui.BAR_PREFIX_EMOJIS:
                if msg.content.strip().startswith(emoji):
                    has_prefix = True
                    matched_prefix = emoji
                    break
            
            log.append(f"Detection: Button={has_bar_btn}, Prefix={has_prefix} ({matched_prefix})")
            
            if has_bar_btn or has_prefix:
                log.append("Result: ✅ VALID BAR MATCH")
                found_any = True
            else:
                log.append("Result: ❌ NO MATCH")

    except Exception as e:
        log.append(f"\nCRITICAL ERROR DURING SCAN: {e}")
        import traceback
        log.append(traceback.format_exc())

    log.append("-" * 40)
    log.append(f"Scanned {count} messages.")
    log.append(f"Found valid bar: {found_any}")

    # Send file
    import io
    out_file = io.BytesIO("\n".join(log).encode("utf-8"))
    await interaction.followup.send(
        content="🔍 **Debug Scan Complete**\nIf a bar is visible but marked 'NO MATCH', the detection logic is failing.\nIf 'VALID BAR MATCH' is found, the issue is in the update/adoption logic.",
        file=discord.File(out_file, filename=f"debug_scan_{interaction.channel_id}.txt")
    )

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
    # Allow self-edits/embeds to be processed.
    # Allow Webhooks (PluralKit) to proceed for checking.
    # Ignore other bots.
    if after.author.bot and after.author.id != client.user.id and after.webhook_id is None: 
        return
    
    if not after.embeds: return
    
    # Check Master Switch
    if not memory_manager.get_server_setting("embed_suppression", True):
        return

    # Resolve Author ID (Handle PluralKit Proxies)
    author_id = after.author.id
    
    if after.webhook_id:
        # Attempt to resolve real sender via PK
        try:
            _, _, _, _, pk_sender, _ = await services.service.get_pk_message_data(after.id)
            if pk_sender:
                author_id = int(pk_sender)
        except Exception as e:
            # Log error but continue with default author_id
            logger.warning(f"Failed to resolve PK sender in on_message_edit: {e}")

    # Check User Opt-in (Force suppress for self if global setting is on)
    suppressed_users = memory_manager.get_suppressed_users()
    is_self = (after.author.id == client.user.id)
    
    if not is_self and str(author_id) not in suppressed_users:
        return

    # Check Embed Type
    # Added 'rich' to catch Twitter/X embeds which often misreport type
    should_suppress = False
    for embed in after.embeds:
        if embed.type in ('link', 'article', 'video', 'rich'):
            should_suppress = True
            break
            
    if should_suppress:
        try:
            await after.edit(suppress=True)
            logger.info(f"🔇 Suppressed embed for {after.author.name} (Real ID: {author_id}) in {after.channel.name}")
        except discord.Forbidden:
            logger.warning(f"❌ Failed to suppress embed in {after.channel.name}: Missing Permissions.")
        except Exception as e:
            logger.warning(f"❌ Failed to suppress embed: {e}")

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
        try: await message.delete()
        except: pass

        cmd_parts = message.content.split()
        cmd = cmd_parts[0].lower()[1:] # Remove '&'
        args = cmd_parts[1:] if len(cmd_parts) > 1 else []
        
        # Map of command name to (Slash Command Object, Argument Name or None)
        cmd_map = {
            "bar": (bar_command, None),
            "b": (bar_command, None),
            "addbar": (addbar_command, None),
            "removebar": (removebar_command, None),
            "drop": (drop_command, None),
            "dropall": (dropall_command, None),
            "d": (drop_command, None),
            "dropcheck": (dropcheck_command, None),
            "c": (dropcheck_command, None),
            "cleanbars": (cleanbars_command, None),
            "idle": (idle_command, None),
            "global": (global_command, "text"),
            "addchannel": (add_channel_command, None),
            "removechannel": (remove_channel_command, None),
            "enableall": (enableall_command, None),
            "disableall": (disableall_command, None),
            "reboot": (reboot_command, None),
            "shutdown": (shutdown_command, None),
            "clearmemory": (clearmemory_command, None),
            "bugreport": (bugreport_command, None),
            "reportbug": (bugreport_command, None), # Alias
            "goodbot": (good_bot_leaderboard, None),
            "synccommands": (synccommands_command, None),
            "debug": (debug_command, None),
            "testmessage": (testmessage_command, None),
            "clearallmemory": (clearallmemory_command, None),
            "cleargoodbots": (cleargoodbots_command, None),
            "wipelogs": (wipelogs_command, None),
            "nukedatabase": (nukedatabase_command, None),
            "backup": (backup_command, "target"),
            "backupuploadonly": (backup_command, "target"),
            "debugtest": (debugtest_command, None),
            "debugscan": (debugscan_command, None),
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
            "console": (console_command, None),
        }

        if cmd in cmd_map:
            command_func, arg_name = cmd_map[cmd]
            
            kwargs = {}
            if arg_name:
                if not args:
                     await message.channel.send(f"❌ Usage: `&{cmd} <{arg_name}>`", delete_after=2.0)
                     return
                kwargs[arg_name] = " ".join(args)
            
            if cmd == "backupuploadonly":
                kwargs["upload_only"] = True
            
            # Create Mock Interaction
            mock_intr = MockInteraction(client, message.channel, message.author, message)
            
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

        if message.content.startswith("&scanemojis"):
            if not helpers.is_authorized(message.author): return
            try:
                limit = 20
                parts = message.content.split()
                if len(parts) > 1 and parts[1].isdigit():
                    limit = int(parts[1])
                
                # Reuse logic? Hard in on_message. Reimplement simply.
                emoji_pattern = re.compile(r'<(a?):(\w+):(\d+)>')
                found_emojis = {}
                count = 0
                
                async for msg in message.channel.history(limit=limit):
                    matches = emoji_pattern.findall(msg.content)
                    for animated, name, id in matches:
                         found_emojis[name] = f"<{animated}:{name}:{id}>"
                         count += 1
                
                if not found_emojis:
                    await message.channel.send("No custom emojis found.")
                else:
                    import io
                    json_data = json.dumps(found_emojis, indent=4)
                    file = discord.File(io.BytesIO(json_data.encode()), filename="emoji_db.json")
                    await message.channel.send(f"✅ Scanned {limit} messages. Found {len(found_emojis)} unique emojis.", file=file)
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

        # --- UPLINK NOTIFICATION CHECK ---
        # If this channel has an active uplink, and the message is not from me (the bot)
        if message.channel.id in client.active_bars and message.author.id != client.user.id:
            # Only update if not already notified to save DB writes
            if not client.active_bars[message.channel.id].get("has_notification", False):
                client.active_bars[message.channel.id]["has_notification"] = True
                memory_manager.set_bar_notification(message.channel.id, True)
                # Update console to show the Exclamark
                await client.update_console_status()

        # --- PROXY/WEBHOOK CHECKS ---
        if message.webhook_id is None:
            try:
                tags = await services.service.get_system_proxy_tags(config.MY_SYSTEM_ID)
                if helpers.matches_proxy_tag(message.content, tags): return
                
                # Ghost Check (Restored & Enhanced)
                # Wait to see if a webhook appears that replaces this message
                await asyncio.sleep(5.0)
                try:
                    await message.channel.fetch_message(message.id)
                    # If we are here, the message STILL exists.
                    # Check if a webhook appeared nearby (race condition check)
                    async for recent in message.channel.history(limit=15):
                        if recent.webhook_id is not None:
                             diff = (recent.created_at - message.created_at).total_seconds()
                             if abs(diff) < 6.0: 
                                 logger.info(f"👻 Ghost detected (Late Webhook): {message.id} replaced by {recent.id}")
                                 skip_reaction_remove = True
                                 return
                except (discord.NotFound, discord.HTTPException): 
                    # Message is gone -> It was ghosted (Proxied)
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
                
                # Webhook / Proxy Resolution (Only for real ID)
                if message.webhook_id:
                    pk_name, _, _, _, pk_sender, _ = await services.service.get_pk_message_data(message.id)
                    if pk_sender:
                        try: sender_id = int(pk_sender)
                        except: pass
                    if pk_name:
                        real_name = pk_name

                now = discord.utils.utcnow().timestamp()
                last_time = client.good_bot_cooldowns.get(sender_id, 0)
                
                if now - last_time > 5:
                    # Resolve Handle
                    handle = message.author.name
                    # If webhook, handle is the webhook name usually, but we want the USER handle if possible?
                    # The user prompt said: "Displayname (@Handle) - score"
                    # For proxies, the webhook author name is the display name. The handle is tricky if it's a webhook.
                    # But we have sender_id. Let's try to fetch the user for the handle.
                    try:
                        user_obj = None
                        if message.guild:
                             user_obj = message.guild.get_member(sender_id)
                             if not user_obj: user_obj = await message.guild.fetch_member(sender_id)
                        else:
                             user_obj = client.get_user(sender_id) or await client.fetch_user(sender_id)
                        
                        if user_obj: handle = user_obj.name
                    except: pass

                    # Format: Display Name (@Handle)
                    formatted_name = f"{real_name} (@{handle})"

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
            # Determine if this was an explicit trigger (Ping/Role) vs just a reply or keyword
            is_explicit_trigger = (client.user in message.mentions)
            if not is_explicit_trigger and message.role_mentions:
                 for role in message.role_mentions:
                     if role.id in TRIGGER_ROLES: is_explicit_trigger = True; break

            global_chat = memory_manager.get_server_setting("global_chat_enabled", False)
            allowed_ids = memory_manager.get_allowed_channels()
            
            # Allow explicit triggers to bypass whitelist
            if not global_chat and message.channel.id not in allowed_ids and not is_explicit_trigger: 
                # logger.debug(f"Ignoring message in {message.channel.name}: Not whitelisted.")
                return

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

                    # Auth Check: Allow if Admin/Special Role OR if it's the Owner's System OR Global Chat is Enabled
                    is_own_system = (system_id == config.MY_SYSTEM_ID)
                    
                    if not global_chat and not is_own_system and not helpers.is_authorized(member_obj or sender_id):
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

                    # Final Ghost Check (Reduce Race Conditions)
                    try:
                        await message.channel.fetch_message(message.id)
                    except discord.NotFound:
                         logger.info(f"👻 Final Ghost Check caught {message.id} before generation.")
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
    if not config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not found.")
    else:
        try:
            client.run(config.BOT_TOKEN)
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard Interrupt received.")
        finally:
            if os.path.exists(config.RESTART_META_FILE):
                logger.info("🔄 Restart flag detected. Exiting with code 0 for restart...")
                sys.exit(0)
            elif os.path.exists(config.SHUTDOWN_FLAG_FILE):
                logger.info("🛑 Shutdown flag detected. Exiting with code 0.")
                sys.exit(0)
            else:
                logger.info("🛑 Process ended naturally.")
                sys.exit(0)
