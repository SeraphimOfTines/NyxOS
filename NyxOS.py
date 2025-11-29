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

# Local Modules
import config
import helpers
import services
import memory_manager
import ui

# ==========================================
# BOT SETUP
# ==========================================

# Ensure logs directory exists
os.makedirs(config.LOGS_DIR, exist_ok=True)

# Configure Logging
logger = logging.getLogger('NyxOS')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# File Handler
file_handler = logging.FileHandler(os.path.join(config.LOGS_DIR, 'nyxos.log'), encoding='utf-8')
file_handler.setFormatter(formatter)

# Apply handlers (avoid duplicates)
if not logger.handlers:
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

# Set root logger level to suppress debug noise from libraries if needed
logging.getLogger().setLevel(logging.INFO)

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
        self.channel_cutoff_times = {}
        self.good_bot_cooldowns = {} 
        self.processing_locks = set() 
        self.active_views = {} 
        self.active_bars = {}
        self.bar_drop_cooldowns = {}
        self.last_bot_message_id = {} 
        self.boot_cleared_channels = set()
        self.has_synced = False
        self.abort_signals = set()

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

    async def setup_hook(self):
        # Clean startup flags
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            try: os.remove(config.SHUTDOWN_FLAG_FILE)
            except: pass
            
        await services.service.start()
        self.add_view(ui.ResponseView())
        self.loop.create_task(self.heartbeat_task())

    async def drop_status_bar(self, channel_id):
        if channel_id not in self.active_bars:
            return
        
        # Cooldown Check (Prevent Race Conditions)
        now = time.time()
        if now - self.bar_drop_cooldowns.get(channel_id, 0) < 2.0:
            return
        self.bar_drop_cooldowns[channel_id] = now
        
        bar_data = self.active_bars[channel_id]
        channel = self.get_channel(channel_id)
        if not channel:
            try: channel = await self.fetch_channel(channel_id)
            except: return

        # --- Handle Old Message (Split Logic) ---
        old_msg_id = bar_data.get("message_id")
        check_msg_id = bar_data.get("checkmark_message_id")
        
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                
                if old_msg_id == check_msg_id:
                    # SPLIT: Old message becomes checkmark archive
                    # Remove View to stop interactions on archived checkmark
                    await old_msg.edit(content=ui.FLAVOR_TEXT["CHECKMARK_EMOJI"], view=None)
                else:
                    # DROP: Old message was just content, delete it
                    await old_msg.delete()
            except discord.NotFound: pass
            except Exception as e: logger.warning(f"Failed to handle old bar: {e}")
        
        # --- Send New Message ---
        view = ui.StatusBarView(bar_data["content"], bar_data["user_id"], channel_id, bar_data["persisting"])
        try:
            new_msg = await channel.send(bar_data["content"], view=view)
            
            # Update State
            self.active_bars[channel_id]["message_id"] = new_msg.id
            self.active_views[new_msg.id] = view 
            
            # If checkmark was previously on old_msg (or this is first run), it stays behind (disjointed).
            # So checkmark_message_id remains what it was (pointing to old_msg_id, now archived).
            # Unless this is init, handled by /bar command.
            
        except Exception as e:
            logger.error(f"Failed to drop status bar: {e}")

    async def on_ready(self):
        # ... (Existing on_ready logic handled below, but we add sync check here)
        pass

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

    async def cleanup_old_bars(self, channel):
        """Scans last 100 messages and deletes any status bars or stray checkmarks found."""
        try:
            async for msg in channel.history(limit=100):
                if msg.author.id == self.user.id:
                    is_target = False
                    
                    # 1. Check Components (Buttons)
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    is_target = True
                                    break
                            if is_target: break
                    
                    # 2. Check Content Prefix (Bar Emojis)
                    if not is_target and msg.content:
                        for emoji in ui.BAR_PREFIX_EMOJIS:
                            if msg.content.strip().startswith(emoji):
                                is_target = True
                                break
                    
                    # 3. Check for Stray Checkmark
                    if not is_target and msg.content:
                        if msg.content.strip() == ui.FLAVOR_TEXT['CHECKMARK_EMOJI']:
                            is_target = True

                    if is_target:
                        try: await msg.delete()
                        except: pass
            
            # Also clear from runtime state if it matches
            if channel.id in self.active_bars:
                del self.active_bars[channel.id]

        except Exception as e:
            logger.warning(f"Bar cleanup failed: {e}")

    async def find_last_bar_content(self, channel):
        """Finds the content of the most recent status bar in the channel (last 100 messages)."""
        try:
            async for msg in channel.history(limit=100):
                if msg.author.id == self.user.id:
                    is_bar = False
                    
                    # 1. Check Components
                    if msg.components:
                        for row in msg.components:
                            for child in row.children:
                                if getattr(child, "custom_id", "").startswith("bar_"):
                                    is_bar = True
                                    break
                            if is_bar: break
                    
                    # 2. Check Content Prefix (Fallback)
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
        """Updates the bar prefix, preserving content, and drops it."""
        # 1. Find existing content
        content = None
        found_raw = await self.find_last_bar_content(interaction.channel)
        
        if found_raw:
            content = found_raw
            # Strip Checkmark
            chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
            if chk in content:
                content = content.replace(chk, "")
            
            # Strip ANY existing prefix
            content = content.strip()
            for emoji in ui.BAR_PREFIX_EMOJIS:
                if content.startswith(emoji):
                    content = content[len(emoji):].strip()
                    break # Only strip one prefix
        
        # If no content found, we can't update "middle symbols".
        # User said: "if it's not present within the last 100 messages" -> implied check done in find_last_bar_content
        if not content:
            await interaction.response.send_message("❌ No active bar found to update.", ephemeral=True, delete_after=2.0)
            return

        # 2. Construct new content
        full_content = f"{new_prefix_emoji} {content} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
        
        # Strip spaces between emojis (horizontally)
        full_content = re.sub(r'>\s+<', '><', full_content)
        
        # 3. Cleanup old
        await self.cleanup_old_bars(interaction.channel)
        
        # 4. Send new
        await interaction.response.defer(ephemeral=True)
        
        view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, False)
        msg = await interaction.channel.send(full_content, view=view)
        
        self.active_bars[interaction.channel_id] = {
            "content": full_content, # Store full content? No, usually content is just middle. 
            # Wait, StatusBarView takes "content" and sends it. 
            # bar_command stores "content" (middle) but sends "full_content".
            # Here full_content HAS the prefix and checkmark.
            # If we store full_content as "content", subsequent updates might double-prefix if not careful.
            # But my strip logic handles ANY prefix.
            "content": full_content, 
            "user_id": interaction.user.id,
            "message_id": msg.id,
            "checkmark_message_id": msg.id,
            "persisting": False
        }
        self.active_views[msg.id] = view
        
        await interaction.delete_original_response()

    async def replace_bar_content(self, interaction, new_content):
        """Replaces the entire bar content (preserving checkmark) and drops it."""
        # Cleanup old
        await self.cleanup_old_bars(interaction.channel)
        
        # Strip spaces between emojis
        new_content = re.sub(r'>\s+<', '><', new_content)
        
        # Send new
        full_content = new_content
        
        await interaction.response.defer(ephemeral=True)
        
        view = ui.StatusBarView(full_content, interaction.user.id, interaction.channel_id, False)
        msg = await interaction.channel.send(full_content, view=view)
        
        self.active_bars[interaction.channel_id] = {
            "content": full_content,
            "user_id": interaction.user.id,
            "message_id": msg.id,
            "checkmark_message_id": msg.id,
            "persisting": False
        }
        self.active_views[msg.id] = view
        
        await interaction.delete_original_response()

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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        await interaction.response.send_message("✅ Channel already whitelisted.", ephemeral=True)
    else:
        memory_manager.add_allowed_channel(interaction.channel_id)
        await interaction.response.send_message(f"😄 I'll talk in this channel!", ephemeral=True)

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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
        
    allowed_ids = memory_manager.get_allowed_channels()
    if interaction.channel_id in allowed_ids:
        memory_manager.remove_allowed_channel(interaction.channel_id)
        await interaction.response.send_message(f"🤐 I'll ignore this channel!", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Channel not in whitelist.", ephemeral=True)

@client.tree.command(name="enableall", description="Enable Global Chat Mode (Talk in ALL channels).")
async def enableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.set_server_setting("global_chat_enabled", True)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_CHAT_ENABLED"], ephemeral=False)

@client.tree.command(name="disableall", description="Disable Global Chat Mode (Talk in whitelist only).")
async def disableall_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.set_server_setting("global_chat_enabled", False)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_CHAT_DISABLED"], ephemeral=False)

@client.tree.command(name="reboot", description="Full restart of the bot process.")
async def reboot_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return

    await interaction.response.send_message(ui.FLAVOR_TEXT["REBOOT_MESSAGE"], ephemeral=False) 
    
    meta = {"channel_id": interaction.channel_id}
    try:
        with open(config.RESTART_META_FILE, "w") as f:
            json.dump(meta, f)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        logger.warning(f"⚠️ Failed to write restart metadata: {e}")

    await client.close()
    # os.execl replaces the process, keeping PID same. Monitor should be aware or tolerant.
    python = sys.executable
    os.execl(python, python, *sys.argv)

@client.tree.command(name="shutdown", description="Gracefully shut down the bot.")
async def shutdown_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return

    # Send to current channel
    await interaction.response.send_message(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"], ephemeral=False)
    
    # Send to Startup/System Channel (if different)
    if config.STARTUP_CHANNEL_ID and config.STARTUP_CHANNEL_ID != interaction.channel_id:
        try:
            sys_channel = await client.fetch_channel(config.STARTUP_CHANNEL_ID)
            if sys_channel:
                await sys_channel.send(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"])
        except Exception as e:
            logger.warning(f"⚠️ Failed to send shutdown msg to system channel: {e}")
    
    # Write shutdown flag so monitor knows it was intentional
    try:
        with open(config.SHUTDOWN_FLAG_FILE, "w") as f:
            f.write("shutdown")
    except: pass

    await client.close()
    sys.exit(0)

@client.tree.command(name="killmyembeds", description="Toggle auto-suppression of hyperlink embeds for your messages.")
async def killmyembeds_command(interaction: discord.Interaction):
    is_enabled = memory_manager.toggle_suppressed_user(interaction.user.id)
    msg = ui.FLAVOR_TEXT["EMBED_SUPPRESSION_ENABLED"] if is_enabled else ui.FLAVOR_TEXT["EMBED_SUPPRESSION_DISABLED"]
    await interaction.response.send_message(msg, ephemeral=True)

@client.tree.command(name="suppressembedson", description="Enable the server-wide embed suppression feature.")
async def suppressembedson_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.set_server_setting("embed_suppression", True)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_SUPPRESSION_ON"], ephemeral=False)

@client.tree.command(name="suppressembedsoff", description="Disable the server-wide embed suppression feature.")
async def suppressembedsoff_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.set_server_setting("embed_suppression", False)
    await interaction.response.send_message(ui.FLAVOR_TEXT["GLOBAL_SUPPRESSION_OFF"], ephemeral=False)

@client.tree.command(name="clearmemory", description="Clear the bot's memory for this channel.")
async def clearmemory_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    
    # Update cutoff time to NOW
    client.channel_cutoff_times[interaction.channel_id] = interaction.created_at
    
    memory_manager.clear_channel_memory(interaction.channel_id, interaction.channel.name)
    await interaction.response.send_message(ui.FLAVOR_TEXT["CLEAR_MEMORY_DONE"], ephemeral=True)

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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        await client.tree.sync()
        # Update hash
        new_hash = client.get_tree_hash()
        with open(config.COMMAND_STATE_FILE, "w") as f:
            f.write(new_hash)
        await interaction.followup.send("✅ Commands force-synced and state updated.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error syncing: {e}")

@client.tree.command(name="debug", description="Toggle Debug Mode (Admin Only).")
async def debug_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    current = memory_manager.get_server_setting("debug_mode", False)
    new_mode = not current
    memory_manager.set_server_setting("debug_mode", new_mode)
    msg = ui.FLAVOR_TEXT["DEBUG_MODE_ON"] if new_mode else ui.FLAVOR_TEXT["DEBUG_MODE_OFF"]
    await interaction.response.send_message(msg, ephemeral=False)

@client.tree.command(name="testmessage", description="Send a test message (Admin/Debug Only).")
async def testmessage_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
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
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.wipe_all_memories()
    await interaction.response.send_message(ui.FLAVOR_TEXT["MEMORY_WIPED"], ephemeral=True)

@client.tree.command(name="wipelogs", description="Wipe ALL logs (Admin/Debug Only).")
async def wipelogs_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return
    memory_manager.wipe_all_logs()
    await interaction.response.send_message(ui.FLAVOR_TEXT["LOGS_WIPED"], ephemeral=True)

@client.tree.command(name="debugtest", description="Run unit tests and report results (Admin Only).")
async def debugtest_command(interaction: discord.Interaction):
    if not helpers.is_authorized(interaction.user):
        await interaction.response.send_message(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return

    await interaction.response.defer()
    
    import io
    import unittest
    import tests.test_suite
    
    # Capture stdout
    log_capture = io.StringIO()
    runner = unittest.TextTestRunner(stream=log_capture, verbosity=2)
    
    # Load Suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestMemoryManager))
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestServices))
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestUI))
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestServerAdmin))
    suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestCommands))
    
    # Run in a separate thread to avoid event loop conflicts
    start_time = time.time()
    result = await asyncio.to_thread(runner.run, suite)
    duration = time.time() - start_time
    output = log_capture.getvalue()
    
    # Log to console/file
    logger.info(f"Debug Test Output:\n{output}")
    
    # Send to Discord
    status = "✅ PASSED" if result.wasSuccessful() else "❌ FAILED"
    msg = f"**Unit Test Results:** {status}\nRan {result.testsRun} tests in {duration:.3f}s."
    
    file = discord.File(io.BytesIO(output.encode()), filename="test_results.txt")
    await interaction.followup.send(msg, file=file)

@client.tree.command(name="bar", description="Create a persistent status bar/sticker.")
async def bar_command(interaction: discord.Interaction, content: str = None):
    # Auto-find content if None
    if content is None:
        found_content = await client.find_last_bar_content(interaction.channel)
        if found_content:
            # Strip existing checkmark if present to avoid duplication
            chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
            if chk in found_content:
                content = found_content.replace(chk, "").strip()
            else:
                content = found_content
        else:
            await interaction.response.send_message("❌ No content provided and no existing bar found to clone.", ephemeral=True)
            return

    await client.cleanup_old_bars(interaction.channel)

    # Strip whitespace from user input or found content
    content = content.strip()
    
    # Remove spaces between emojis (e.g. > < becomes ><)
    content = re.sub(r'>\s+<', '><', content)

    # Initial content includes checkmark
    full_content = f"{content} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"

    await interaction.response.defer(ephemeral=True)
    await interaction.delete_original_response()
    
    # Create manually first time to init IDs correctly
    view = ui.StatusBarView(content, interaction.user.id, interaction.channel_id, False)
    msg = await interaction.channel.send(full_content, view=view)
    
    client.active_bars[interaction.channel_id] = {
        "content": content,
        "user_id": interaction.user.id,
        "message_id": msg.id,
        "checkmark_message_id": msg.id, # Initially together
        "persisting": False
    }
    client.active_views[msg.id] = view

@client.tree.command(name="dropcheck", description="Bring the checkmark down to the current bar.")
async def dropcheck_command(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar.", ephemeral=True)
        return

    bar_data = client.active_bars[channel_id]
    curr_msg_id = bar_data.get("message_id")
    check_msg_id = bar_data.get("checkmark_message_id")

    if curr_msg_id == check_msg_id:
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        return

    await interaction.response.defer(ephemeral=True)
    
    # 1. Delete old checkmark (Archive)
    if check_msg_id:
        try:
            old_check = await interaction.channel.fetch_message(check_msg_id)
            await old_check.delete()
        except: pass

                # 2. Update current bar to include checkmark
    if curr_msg_id:
        try:
            curr_msg = await interaction.channel.fetch_message(curr_msg_id)
            sep = "\n" if "\n" in bar_data["content"] else " "
            new_content = f"{bar_data['content']}{sep}{ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
            await curr_msg.edit(content=new_content)
            
            # Update state
            client.active_bars[channel_id]["checkmark_message_id"] = curr_msg_id
            await interaction.delete_original_response()
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update bar: {e}", ephemeral=True)

@client.tree.command(name="thinking", description="Set status to Thinking.")
async def thinking_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Thinking:1322962569300017214>")

@client.tree.command(name="reading", description="Set status to Reading.")
async def reading_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Reading:000000000000000000>")

@client.tree.command(name="backlogging", description="Set status to Backlogging.")
async def backlogging_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Backlogging:000000000000000000>")

@client.tree.command(name="sleeping", description="Set status to Sleeping.")
async def sleeping_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Sleeping:1312772391759249410>")

@client.tree.command(name="typing", description="Set status to Typing.")
async def typing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Typing:000000000000000000>")

@client.tree.command(name="brb", description="Set status to BRB.")
async def brb_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:BRB:000000000000000000>")

@client.tree.command(name="processing", description="Set status to Processing.")
async def processing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Processing:000000000000000000>")

@client.tree.command(name="angel", description="Set status to Angel.")
async def angel_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Angel:000000000000000000>")

@client.tree.command(name="pausing", description="Set status to Pausing.")
async def pausing_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:Pausing:1385258657532481597>")

@client.tree.command(name="notwatching", description="Set status to Not Watching.")
async def notwatching_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:NotWatching:1301840196966285322>")

@client.tree.command(name="watchingslowly", description="Set status to Watching Slowly/Occasionally.")
async def watchingslowly_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:WatchingOccasionally:1301837550159269888>")

@client.tree.command(name="watchingclosely", description="Set status to Watching Closely.")
async def watchingclosely_command(interaction: discord.Interaction):
    await client.update_bar_prefix(interaction, "<a:WatchingClosely:1301838354832425010>")

@client.tree.command(name="linkcheck", description="Get a link to the current checkmark message.")
async def linkcheck_command(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar.", ephemeral=True, delete_after=2.0)
        return

    check_msg_id = client.active_bars[channel_id].get("checkmark_message_id")
    if not check_msg_id:
        await interaction.response.send_message("❌ No checkmark found.", ephemeral=True, delete_after=2.0)
        return

    guild_id = interaction.guild_id if interaction.guild else "@me"
    link = f"https://discord.com/channels/{guild_id}/{channel_id}/{check_msg_id}"
    
    await interaction.response.send_message(f"[Jump to Checkmark]({link})", ephemeral=True, delete_after=2.0)

@client.tree.command(name="drop", description="Drop (refresh) the current status bar.")
async def drop_command(interaction: discord.Interaction):
    if interaction.channel_id not in client.active_bars:
        await interaction.response.send_message("❌ No active bar in this channel. Use `/bar` to create one.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    await client.drop_status_bar(interaction.channel_id)
    await interaction.delete_original_response()

@client.tree.command(name="help", description="Show the help index.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="NyxOS Help Index", color=discord.Color.blue())
    embed.add_field(name="General Commands", value="`/killmyembeds` - Toggle auto-suppression of link embeds.\n`/goodbot` - Show the Good Bot leaderboard.\n`/reportbug` - Submit a bug report.", inline=False)
    embed.add_field(name="Admin Commands", value="`/enableall` - Enable Global Chat (All Channels).\n`/disableall` - Disable Global Chat (Whitelist Only).\n`/addchannel` - Whitelist channel.\n`/removechannel` - Blacklist channel.\n`/suppressembedson/off` - Toggle server-wide embed suppression.\n`/clearmemory` - Clear current channel memory.\n`/reboot` - Restart bot.\n`/shutdown` - Shutdown bot.\n`/debug` - Toggle Debug Mode.\n`/testmessage` - Send test msg (Debug).\n`/clearallmemory` - Wipe ALL memories (Debug).\n`/wipelogs` - Wipe ALL logs (Debug).\n`/synccommands` - Force sync slash commands.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# EVENTS
# ==========================================

@client.event
async def on_ready():
    logger.info('# ==========================================')
    logger.info('#                NyxOS v2.0')
    logger.info('#         Lovingly made by Calyptra')
    logger.info('#       https://temple.HyperSystem.xyz')    
    logger.info('# ==========================================')
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    logger.info(f'Targeting LM Studio at: {config.LM_STUDIO_URL}')
    
    client.has_synced = True
    
    # Check commands
    await client.check_and_sync_commands()

    # Check for restart metadata
    restart_data = None
    if os.path.exists(config.RESTART_META_FILE):
        try:
            with open(config.RESTART_META_FILE, "r") as f:
                restart_data = json.load(f)
            os.remove(config.RESTART_META_FILE)
        except: pass

    target_channel_id = None
    if restart_data and restart_data.get("channel_id"):
        target_channel_id = restart_data.get("channel_id")
    elif config.STARTUP_CHANNEL_ID:
        target_channel_id = config.STARTUP_CHANNEL_ID

    if target_channel_id:
        try:
            channel = await client.fetch_channel(target_channel_id)
            if channel:
                await channel.send(ui.FLAVOR_TEXT["STARTUP_MESSAGE"])
        except Exception as e:
            logger.warning(f"⚠️ Failed to send startup message: {e}")

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
             client.loop.create_task(client.drop_status_bar(message.channel.id))

    # --- PREFIX COMMANDS ---
    if message.content.startswith("&"):
        cmd = message.content.split()[0].lower()
        
        # &bar
        if cmd == "&bar":
            # Cooldown to prevent race conditions (User + Webhook)
            if time.time() - client.bar_drop_cooldowns.get(message.channel.id, 0) < 2.0:
                return

            content = message.content[5:].strip()
            
            # Auto-find content if empty
            if not content:
                found_content = await client.find_last_bar_content(message.channel)
                if found_content:
                    # Strip existing checkmark
                    chk = ui.FLAVOR_TEXT['CHECKMARK_EMOJI']
                    if chk in found_content:
                        content = found_content.replace(chk, "").strip()
                    else:
                        content = found_content
            
            if not content:
                await message.channel.send("❌ Usage: `&bar <text/emojis>` or have an existing bar to clone.")
                return
            
            try: await message.delete()
            except: pass
            
            await client.cleanup_old_bars(message.channel)

            content = content.strip()
            # Remove spaces between emojis
            content = re.sub(r'>\s+<', '><', content)

            # Initial content includes checkmark
            full_content = f"{content} {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
            
            view = ui.StatusBarView(content, message.author.id, message.channel.id, False)
            msg = await message.channel.send(full_content, view=view)

            client.active_bars[message.channel.id] = {
                "content": content,
                "user_id": message.author.id,
                "message_id": msg.id,
                "checkmark_message_id": msg.id,
                "persisting": False
            }
            client.active_views[msg.id] = view
            return

        # &dropcheck
        if cmd == "&dropcheck":
            try: await message.delete()
            except: pass
            
            channel_id = message.channel.id
            if channel_id not in client.active_bars:
                return

            bar_data = client.active_bars[channel_id]
            curr_msg_id = bar_data.get("message_id")
            check_msg_id = bar_data.get("checkmark_message_id")

            if curr_msg_id == check_msg_id: return

            # 1. Delete old checkmark
            if check_msg_id:
                try:
                    old_check = await message.channel.fetch_message(check_msg_id)
                    await old_check.delete()
                except: pass

            # 2. Update current bar
            if curr_msg_id:
                try:
                    curr_msg = await message.channel.fetch_message(curr_msg_id)
                    sep = "\n" if "\n" in bar_data["content"] else " "
                    new_content = f"{bar_data['content']}{sep}{ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
                    await curr_msg.edit(content=new_content)
                    client.active_bars[channel_id]["checkmark_message_id"] = curr_msg_id
                except: pass
            return

        # &linkcheck
        if cmd == "&linkcheck":
            try: await message.delete()
            except: pass
            
            channel_id = message.channel.id
            if channel_id not in client.active_bars:
                await message.channel.send("❌ No active bar.", delete_after=2.0)
                return

            check_msg_id = client.active_bars[channel_id].get("checkmark_message_id")
            if not check_msg_id:
                await message.channel.send("❌ No checkmark found.", delete_after=2.0)
                return

            # Construct link manually since we have IDs
            guild_id = message.guild.id if message.guild else "@me"
            link = f"https://discord.com/channels/{guild_id}/{channel_id}/{check_msg_id}"
            
            await message.channel.send(f"[Jump to Checkmark]({link})", delete_after=2.0)
            return

        # Status Shortcuts
        status_map = {
            "&thinking": "<a:Thinking:1322962569300017214>",
            "&reading": "<a:Reading:000000000000000000>",
            "&backlogging": "<a:Backlogging:000000000000000000>",
            "&sleeping": "<a:Sleeping:1312772391759249410>",
            "&typing": "<a:Typing:000000000000000000>",
            "&processing": "<a:Processing:000000000000000000>",
            "&angel": "<a:Angel:000000000000000000>",
            "&pausing": "<a:Pausing:1385258657532481597>",
            "&notwatching": "<a:NotWatching:1301840196966285322>",
            "&watchingslowly": "<a:WatchingOccasionally:1301837550159269888>",
            "&watchingclosely": "<a:WatchingClosely:1301838354832425010>"
        }
        
        if cmd in status_map or cmd == "&darkangel":
            try: await message.delete()
            except: pass
            
            # If we are changing status on a bar that HAS the checkmark, we must SPLIT it.
            # Because update_bar_prefix creates a NEW message with the new prefix + old content + checkmark.
            # Wait, update_bar_prefix Logic:
            # 1. Finds old content (strips checkmark)
            # 2. Constructs new content (prefix + content + checkmark)
            # 3. cleanup_old_bars -> DELETES old message
            # 4. Sends new message.
            #
            # If checkmark was on the old message, it gets deleted and re-sent on the new one.
            # This effectively "drops" the bar.
            # The user requirement was: "/notwatching... will always drop the bar... keeping the rest of the emoji intact."
            # So dropping is correct behavior for status updates.
            
            # HOWEVER, if we want to emulate `drop_status_bar` logic where checkmark stays behind if disjointed...
            # `update_bar_prefix` essentially re-creates the bar.
            # If we want the checkmark to stay behind (split), we need to handle it.
            # But `update_bar_prefix` appends `CHECKMARK_EMOJI` to the new content.
            # So it brings the checkmark along.
            
            # Re-reading the user request: "The new symbols... make the bar search look for the first emoji... to move it down since it can be ambiguous."
            # "/notwatching... will always drop the bar and replace any symbols in the leftmost slot... keeping the rest... intact."
            # It sounds like "dropping" means moving it to the bottom. Bringing the checkmark is usually implied by "dropping".
            # If the user wants to leave the checkmark behind, they would use `/drop` then update?
            # No, standard behavior for `&bar` / `/bar` is to bring checkmark.
            # `update_bar_prefix` uses `cleanup_old_bars` which deletes the old message.
            
            # Wait, `cleanup_old_bars` deletes the old message. If checkmark was there, it's gone.
            # Then `update_bar_prefix` sends new message with checkmark.
            # So checkmark moves. This seems correct for "dropping the bar".
            
            # Create a mock interaction object to reuse update_bar_prefix
            class MockInteraction:
                def __init__(self, client, channel, user):
                    self.client = client
                    self.channel = channel
                    self.channel_id = channel.id
                    self.user = user
                    self.guild = channel.guild if hasattr(channel, 'guild') else None
                    self.guild_id = channel.guild.id if hasattr(channel, 'guild') and channel.guild else None
                    self.response = self.MockResponse(channel)
                
                class MockResponse:
                    def __init__(self, channel):
                        self.channel = channel
                    async def send_message(self, content, ephemeral=False, delete_after=None):
                        if delete_after:
                            await self.channel.send(content, delete_after=delete_after)
                        else:
                            await self.channel.send(content)
                    async def defer(self, ephemeral=False): pass
                    async def delete_original_response(self): pass

            mock_intr = MockInteraction(client, message.channel, message.author)
            
            if cmd == "&angel":
                await client.replace_bar_content(mock_intr, ui.ANGEL_CONTENT)
            elif cmd == "&darkangel": # Add darkangel handler
                 await client.replace_bar_content(mock_intr, ui.DARK_ANGEL_CONTENT)
            else:
                await client.update_bar_prefix(mock_intr, status_map[cmd])
            return

        # &drop

        # &addchannel
        if cmd == "&addchannel":
            member_obj = message.guild.get_member(message.author.id) if message.guild else None
            if not member_obj:
                try: member_obj = await message.guild.fetch_member(message.author.id)
                except: pass
            if not member_obj: member_obj = message.author

            if not helpers.is_authorized(member_obj):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            
            allowed_ids = memory_manager.get_allowed_channels()
            if message.channel.id in allowed_ids:
                await message.channel.send("✅ Channel already whitelisted.")
            else:
                memory_manager.add_allowed_channel(message.channel.id)
                await message.channel.send(f"😄 I'll talk in this channel!")
            return

        # &removechannel
        if cmd == "&removechannel":
            member_obj = message.guild.get_member(message.author.id) if message.guild else None
            if not member_obj:
                try: member_obj = await message.guild.fetch_member(message.author.id)
                except: pass
            if not member_obj: member_obj = message.author

            if not helpers.is_authorized(member_obj):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
                
            allowed_ids = memory_manager.get_allowed_channels()
            if message.channel.id in allowed_ids:
                memory_manager.remove_allowed_channel(message.channel.id)
                await message.channel.send(f"🤐 I'll ignore this channel!")
            else:
                await message.channel.send("⚠️ Channel not in whitelist.")
            return

        # &enableall
        if cmd == "&enableall":
            member_obj = message.guild.get_member(message.author.id) if message.guild else None
            if not member_obj:
                try: member_obj = await message.guild.fetch_member(message.author.id)
                except: pass
            if not member_obj: member_obj = message.author

            if not helpers.is_authorized(member_obj):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            memory_manager.set_server_setting("global_chat_enabled", True)
            await message.channel.send(ui.FLAVOR_TEXT["GLOBAL_CHAT_ENABLED"])
            return

        # &disableall
        if cmd == "&disableall":
            member_obj = message.guild.get_member(message.author.id) if message.guild else None
            if not member_obj:
                try: member_obj = await message.guild.fetch_member(message.author.id)
                except: pass
            if not member_obj: member_obj = message.author

            if not helpers.is_authorized(member_obj):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            memory_manager.set_server_setting("global_chat_enabled", False)
            await message.channel.send(ui.FLAVOR_TEXT["GLOBAL_CHAT_DISABLED"])
            return

        # &reboot
        if cmd == "&reboot":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            await message.channel.send(ui.FLAVOR_TEXT["REBOOT_MESSAGE"])
            meta = {"channel_id": message.channel.id}
            try:
                with open(config.RESTART_META_FILE, "w") as f:
                    json.dump(meta, f)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                logger.warning(f"⚠️ Failed to write restart metadata: {e}")
            await client.close()
            python = sys.executable
            os.execl(python, python, *sys.argv)

        # &shutdown
        if cmd == "&shutdown":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            await message.channel.send(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"])
            
            # Send to Startup/System Channel (if different)
            if config.STARTUP_CHANNEL_ID and config.STARTUP_CHANNEL_ID != message.channel.id:
                try:
                    sys_channel = await client.fetch_channel(config.STARTUP_CHANNEL_ID)
                    if sys_channel:
                        await sys_channel.send(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"])
                except: pass

            try:
                with open(config.SHUTDOWN_FLAG_FILE, "w") as f:
                    f.write("shutdown")
            except: pass
            await client.close()
            sys.exit(0)

        # &clearmemory
        if cmd == "&clearmemory":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            
            # Update cutoff time to NOW
            client.channel_cutoff_times[message.channel.id] = message.created_at
            
            memory_manager.clear_channel_memory(message.channel.id, message.channel.name)
            await message.channel.send(ui.FLAVOR_TEXT["CLEAR_MEMORY_DONE"])
            return

        # &reportbug
        if cmd == "&reportbug":
            await message.channel.send(ui.FLAVOR_TEXT["REPORT_BUG_SLASH_ONLY"])
            return

        # &goodbot
        if cmd == "&goodbot":
            leaderboard = memory_manager.get_good_bot_leaderboard()
            if not leaderboard:
                await message.channel.send(ui.FLAVOR_TEXT["NO_GOOD_BOTS"])
                return
            total_good_bots = sum(user['count'] for user in leaderboard)
            chart_text = ui.FLAVOR_TEXT["GOOD_BOT_HEADER"]
            for i, user_data in enumerate(leaderboard[:10], 1):
                chart_text += f"**{i}.** {user_data['username']} — **{user_data['count']}**\n"
            chart_text += f"\n**Total:** {total_good_bots} Good Bots 💙"
            await message.channel.send(chart_text)
            return

        # &synccommands
        if cmd == "&synccommands":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            await message.channel.send("🔄 Syncing commands...")
            try:
                await client.tree.sync()
                new_hash = client.get_tree_hash()
                with open(config.COMMAND_STATE_FILE, "w") as f:
                    f.write(new_hash)
                await message.channel.send("✅ Commands force-synced and state updated.")
            except Exception as e:
                await message.channel.send(f"❌ Error syncing: {e}")
            return

        # &debug
        if cmd == "&debug":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            current = memory_manager.get_server_setting("debug_mode", False)
            new_mode = not current
            memory_manager.set_server_setting("debug_mode", new_mode)
            msg = ui.FLAVOR_TEXT["DEBUG_MODE_ON"] if new_mode else ui.FLAVOR_TEXT["DEBUG_MODE_OFF"]
            await message.channel.send(msg)
            return

        # &testmessage
        if cmd == "&testmessage":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            
            async with message.channel.typing():
                # Bypass system prompt logic with a blank slate
                response = await services.service.query_lm_studio(
                    user_prompt="Reply to this message with SYSTEM TEST MESSAGE and nothing else.",
                    username="Admin",
                    identity_suffix="",
                    history_messages=[],
                    channel_obj=message.channel,
                    system_prompt_override=" " # Non-empty to bypass template logic, but effectively blank
                )
                
                # Post-process
                response = response.replace("(Seraph)", "").replace("(Chiara)", "").replace("(Not Seraphim)", "")
                response = re.sub(r'\s*\(re:.*?\)', '', response).strip()
                response = helpers.restore_hyperlinks(response)

                view = ui.ResponseView("TEST MESSAGE", message.author.id, "Admin", "", [], message.channel, None, None, None, "")
                await message.channel.send(response, view=view)
            return

        # &clearallmemory
        if cmd == "&clearallmemory":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            memory_manager.wipe_all_memories()
            await message.channel.send(ui.FLAVOR_TEXT["MEMORY_WIPED"])
            return

        # &wipelogs
        if cmd == "&wipelogs":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return
            memory_manager.wipe_all_logs()
            await message.channel.send(ui.FLAVOR_TEXT["LOGS_WIPED"])
            return

        # &debugtest
        if cmd == "&debugtest":
            if not helpers.is_authorized(message.author):
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
                return

            async with message.channel.typing():
                import io
                import unittest
                import tests.test_suite
                
                # Capture stdout
                log_capture = io.StringIO()
                runner = unittest.TextTestRunner(stream=log_capture, verbosity=2)
                
                # Load Suite
                loader = unittest.TestLoader()
                suite = unittest.TestSuite()
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestHelpers))
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestMemoryManager))
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestServices))
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestUI))
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestServerAdmin))
                suite.addTests(loader.loadTestsFromTestCase(tests.test_suite.TestCommands))
                
                # Run in a separate thread to avoid event loop conflicts
                start_time = time.time()
                result = await asyncio.to_thread(runner.run, suite)
                duration = time.time() - start_time
                output = log_capture.getvalue()
                
                # Log to console/file
                logger.info(f"Debug Test Output:\n{output}")
                
                # Send to Discord
                status = "✅ PASSED" if result.wasSuccessful() else "❌ FAILED"
                msg = f"**Unit Test Results:** {status}\nRan {result.testsRun} tests in {duration:.3f}s."
                
                file = discord.File(io.BytesIO(output.encode()), filename="test_results.txt")
                await message.channel.send(msg, file=file)
            return

        # &help
        if cmd == "&help":
            embed = discord.Embed(title="NyxOS Help Index", color=discord.Color.blue())
            embed.add_field(name="General Commands", value="`&killmyembeds` - Toggle auto-suppression of link embeds.\n`&goodbot` - Show the Good Bot leaderboard.\n`&reportbug` - How to report bugs.", inline=False)
            embed.add_field(name="Admin Commands", value="`&enableall` - Enable Global Chat (All Channels).\n`&disableall` - Disable Global Chat (Whitelist Only).\n`&addchannel` - Whitelist channel.\n`&removechannel` - Blacklist channel.\n`&suppressembedson/off` - Toggle server-wide embed suppression.\n`&clearmemory` - Clear current channel memory.\n`&reboot` - Restart bot.\n`&shutdown` - Shutdown bot.\n`&debug` - Toggle Debug Mode.\n`&testmessage` - Send test msg (Debug).\n`&debugtest` - Run Unit Tests (Debug).\n`&clearallmemory` - Wipe ALL memories (Debug).\n`&wipelogs` - Wipe ALL logs (Debug).\n`&synccommands` - Force sync slash commands.", inline=False)
            await message.channel.send(embed=embed)
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
        if should_respond:
            try:
                await message.add_reaction(ui.FLAVOR_TEXT["WAKE_WORD_REACTION"])
                reaction_added = True
            except: pass

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
                    client.good_bot_cooldowns[sender_id] = now
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
                    response_text = await services.service.query_lm_studio(
                        clean_prompt, clean_name, identity_suffix, history_messages, 
                        message.channel, image_data_uri, member_description, search_context, current_reply_context
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
        client.run(config.BOT_TOKEN)
