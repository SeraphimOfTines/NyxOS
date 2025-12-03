import discord
import asyncio
import re
from datetime import datetime
import config
import services
import memory_manager
import helpers
import logging
import sys
import os

logger = logging.getLogger("UI")

# ==========================================
# FLAVOR TEXT & UI CONFIGURATION
# ==========================================
FLAVOR_TEXT = {
    "RETRY_BUTTON": "🔃 Retry",
    "RETRY_THINKING": "# <a:Pausing:1385258657532481597> Thinking . . .",
    "RETRY_DONE": "Regenerated!",
    "DELETE_BUTTON": "🗑️",
    "DELETE_MESSAGE": "# <a:SeraphCometFire:1326369374755491881> Message deleted <a:SeraphCometFire:1326369374755491881>",
    "GOOD_BOT_BUTTON": "Good Bot! 💙",
    "GOOD_BOT_COOLDOWN": "🤚🏻 Fucking CHILL! 😒",
    "BUG_REPORT_BUTTON": "🐛",
    "BUG_REPORT_THANKS": "<a:SeraphHyperYes:1331530716508459018> Thanks for the help! You're the best! 😉",
    "CLEAR_MEMORY_BUTTON": "🧠 Clear Memory",
    "CLEAR_MEMORY_DONE": "🤯 Memory Cleared",
    "NOT_AUTHORIZED": "🤨 You're not my admin. Shoo!",
    "NO_GOOD_BOTS": "No one has called me a good bot yet! <:SeraphCryCute:1402341656698687540>",
    "GOOD_BOT_HEADER": "# <a:SeraphHeartSATVRN:1444517518470287410> I'm such a good bot! <a:SeraphHeartSATVRN:1444517518470287410>\n\n",
    "STARTUP_MESSAGE": "# <a:SATVRNCommand:1301834555086602240> I'm back online! Hi!",
    "REBOOT_MESSAGE": "# <a:Thinking:1322962569300017214> Rebooting . . .",
    "SHUTDOWN_MESSAGE": "# <a:Sleeping:1312772391759249410> System Shutdown. Goodnight!",
    "CRASH_MESSAGE": "# FUCK I just crashed! <a:SeraphCryHandsSnap:1297004800117837906>",
    "REPORT_BUG_SLASH_ONLY": "ℹ️ Please use the `/reportbug` slash command to submit a report.",
    "EMBED_SUPPRESSION_ENABLED": "🔇 Hyperlink embeds will now be auto-suppressed for you.",
    "EMBED_SUPPRESSION_DISABLED": "🔊 Hyperlink embeds will no longer be suppressed for you.",
    "GLOBAL_SUPPRESSION_ON": "<a:SeraphHyperYes:1331530716508459018> Server-wide embed suppression feature is now **ENABLED**.",
    "GLOBAL_SUPPRESSION_OFF": "<a:SeraphHyperNo:1331531123851006025> Server-wide embed suppression feature is now **DISABLED**.",
    "DEBUG_MODE_ON": "🔧 Debug Mode **ENABLED**.",
    "DEBUG_MODE_OFF": "🔧 Debug Mode **DISABLED**.",
    "TEST_MESSAGE": "🧪 This is a test message!",
    "MEMORY_WIPED": "🧹🧹 All memory files have been wiped!",
    "LOGS_WIPED": "🔥 All log files have been wiped!",
    "GLOBAL_CHAT_ENABLED": "🌍 Global Chat Mode **ENABLED**. I will now respond in all channels!",
    "GLOBAL_CHAT_DISABLED": "🔒 Global Chat Mode **DISABLED**. I will only respond in whitelisted channels.",
    "GOOD_BOT_REACTION": "<a:SeraphHeartSATVRN:1444517518470287410>",
    "WAKE_WORD_REACTION": "<a:Thinking:1322962569300017214>",
    "BAR_DROP_ALL": "⏬",
    "BAR_DROP_CHECK": "✅",
    "BAR_DELETE": "🗑️",
    "BAR_PERSIST_OFF": "🔃",
    "BAR_PERSIST_ON": "🔃",
    "CHECKMARK_EMOJI": "<a:AllCaughtUp:1289323947082387526>",
    "REBOOT_HEADER": "# Rebooting . . . <a:RebootingMainframe:1444740155784036512>",
    "REBOOT_SUB": "-# Good morning! ",
    "STARTUP_HEADER": "# System Online <a:SeraphOnline:1445560311397613719>",
    "STARTUP_SUB": "-# Good morning! <a:SeraphHeartRainbowPulse:1307567594433155073>",
    "STARTUP_SUB_DONE": "-# NyxOS v2.0",
    "SHUTDOWN_HEADER": "# Offline <a:SeraphOffline:1445560234016903189>",
    "SYSTEM_OFFLINE": "-# System Unavailable.",
    "UPLINKS_HEADER": "# Active Uplinks",
    "COSMETIC_DIVIDER": "<a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562><a:divider:1420151062614118562>",
    "CUSTOM_CHECKMARK": "<a:SeraphHyperYes:1331530716508459018>",
    "REBOOT_EMOJI": "<a:RebootingMainframe:1444740155784036512>",
    "SHUTDOWN_EMOJI": "<a:SeraphOffline:1445560234016903189>",
    "UPLINK_BULLET": "<a:divider:1420151062614118562>",
    "SYMBOL_KEY": (
        "**Status Symbol Key**\n"
        "<a:WatchingOccasionally:1301837550159269888> **Watching**: Standard monitoring mode.\n"
        "<a:WatchingClosely:1301838354832425010> **Watching Closely**: High alert / Active conversation.\n"
        "<a:NotWatching:1301840196966285322> **Not Watching**: Idle mode.\n"
        "<a:Thinking:1322962569300017214> **Thinking**: Processing a response.\n"
        "<a:Sleeping:1312772391759249410> **Sleeping**: Deep sleep mode (ignore all)."
    )
}

BAR_PREFIX_EMOJIS = [
    "<a:WatchingOccasionally:1301837550159269888>",
    "<a:WatchingClosely:1301838354832425010>",
    "<a:NotWatching:1301840196966285322>",
    "<a:Thinking:1322962569300017214>", 
    "<a:Sleeping:1312772391759249410>", 
    "<a:RebootingMainframe:1444740155784036512>", 
    "<a:SeraphOffline:1445560234016903189>", 
    "<a:Reading:1378593438265770034>",
    "<a:Backlogging:1290067150861500588>", 
    "<a:Typing:1223747307657232405>",
    "<a:Processing:1223643308140793969>",
    "<a:SeraphBRB:1445618635719577671>",
    "<a:Pausing:1385258657532481597>",
]

ANGEL_CONTENT = "<a:SacredMagicStrong:1316971256830103583><a:SeraphWingLeft:1297050718754312192><a:SacredEyeLuminara:1296698905744113715><a:SeraphWingRight:1297051921651073055><a:SacredMagicStrong:1316971256830103583> \n<a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466><a:SacredWind:1296975869566259396><a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466>"
DARK_ANGEL_CONTENT = "<a:SacredMagicStrong:1316971256830103583><a:SeraphWingLeft:1297050718754312192><a:SacredEyeYami:1418478480336879716><a:SeraphWingRight:1297051921651073055><a:SacredMagicStrong:1316971256830103583> \n<a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466><a:SacredWind:1296975869566259396><a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466>"

# ==========================================
# BUG REPORT MODAL & VIEW
# ==========================================

class BugReportButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Submit Report", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BugReportModal(None))

class BugReportModal(discord.ui.Modal, title="Report a Bug"):
    report_title = discord.ui.TextInput(label="Bug Title", style=discord.TextStyle.short, required=True, max_length=100, placeholder="Short summary of the bug")
    report_body = discord.ui.TextInput(label="Bug Description", style=discord.TextStyle.paragraph, required=True, placeholder="Detailed description of what happened...", min_length=10)

    def __init__(self, message_url, original_message_id=None, channel_id=None):
        super().__init__()
        self.message_url = message_url
        self.original_message_id = original_message_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.client.get_channel(config.BUG_REPORT_CHANNEL_ID)
        if not channel:
            try:
                channel = await interaction.client.fetch_channel(config.BUG_REPORT_CHANNEL_ID)
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
            await interaction.response.send_message("✅", ephemeral=True, delete_after=0.5)
            
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
                    logger.error(f"Failed to update bug report button: {e}")

        except Exception as e:
             await interaction.response.send_message(f"❌ Error sending report: {e}", ephemeral=True)

# ==========================================
# REBOOT VIEW
# ==========================================

class RebootView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(label="System Rebooting . . .", style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(btn)

class ShutdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(label="Mainframe Shutdown", style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(btn)

# ==========================================
# STATUS BAR VIEW
# ==========================================

class StatusBarView(discord.ui.View):
    def __init__(self, content, original_user_id, channel_id, persisting=False):
        super().__init__(timeout=None)
        self.content = content
        self.original_user_id = original_user_id
        self.channel_id = channel_id
        self.persisting = persisting
        
        # 1. Drop All
        btn_drop_all = discord.ui.Button(label=FLAVOR_TEXT["BAR_DROP_ALL"], style=discord.ButtonStyle.secondary, custom_id="bar_drop_all_btn")
        btn_drop_all.callback = self.drop_all_callback
        self.add_item(btn_drop_all)

        # 2. Drop Check (DISABLED)
        # btn_drop_check = discord.ui.Button(label=FLAVOR_TEXT["BAR_DROP_CHECK"], style=discord.ButtonStyle.secondary, custom_id="bar_drop_check_btn")
        # btn_drop_check.callback = self.drop_check_callback
        # self.add_item(btn_drop_check)

        # 3. Auto Mode
        btn_persist = discord.ui.Button(label="Auto", style=discord.ButtonStyle.secondary, custom_id="bar_persist_btn")
        btn_persist.callback = self.persist_callback
        self.add_item(btn_persist)

        # 4. Symbols Key
        btn_symbols = discord.ui.Button(label="Symbols", url="https://discord.com/channels/411597692037496833/1302399809113821244/1363651092336083054")
        self.add_item(btn_symbols)

        # 5. Console Link
        # Link to the Startup/Console channel (Defaulting to Temple Guild if not specified)
        console_url = f"https://discord.com/channels/{config.TEMPLE_GUILD_ID}/{config.STARTUP_CHANNEL_ID}"
        btn_console = discord.ui.Button(emoji="🖥️", url=console_url)
        self.add_item(btn_console)

        # 6. Delete (DISABLED - Handled via on_message_delete)
        # btn_delete = discord.ui.Button(label=FLAVOR_TEXT["BAR_DELETE"], style=discord.ButtonStyle.secondary, custom_id="bar_delete_btn")
        # btn_delete.callback = self.delete_callback
        # self.add_item(btn_delete)

        # Update persist button state on init
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if getattr(child, "custom_id", "") == "bar_persist_btn":
                child.label = "Auto" if self.persisting else "Manual"
                child.style = discord.ButtonStyle.success if self.persisting else discord.ButtonStyle.secondary

    async def check_auth(self, interaction, button):
        # Only Admin
        if helpers.is_admin(interaction.user):
            return True
        
        # Unauthorized
        await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        return False

    async def drop_all_callback(self, interaction: discord.Interaction):
        button = discord.utils.get(self.children, custom_id="bar_drop_all_btn")
        if not await self.check_auth(interaction, button): return
        
        await interaction.response.defer()
        
        cid = interaction.channel_id
        # Redundant touch removed (drop_status_bar handles it)

        if hasattr(interaction.client, "drop_status_bar"):
            # Drop All: Move Bar + Move Check
            await interaction.client.drop_status_bar(cid, move_bar=True, move_check=True)
        else:
            await interaction.followup.send("❌ Error: Functionality not found.", ephemeral=True)

    async def drop_check_callback(self, interaction: discord.Interaction):
        button = discord.utils.get(self.children, custom_id="bar_drop_check_btn")
        if not await self.check_auth(interaction, button): return
        
        await interaction.response.defer()

        cid = interaction.channel_id
        # Redundant touch removed (drop_status_bar handles it)

        if hasattr(interaction.client, "drop_status_bar"):
            # Drop Check: Moves Check to Bar (and drags bar to bottom if needed per request)
            await interaction.client.drop_status_bar(cid, move_bar=True, move_check=True)
        else:
            await interaction.followup.send("❌ Error: Functionality not found.", ephemeral=True)

    async def persist_callback(self, interaction: discord.Interaction):
        button = discord.utils.get(self.children, custom_id="bar_persist_btn")
        if not await self.check_auth(interaction, button): return
        
        self.persisting = not self.persisting
        cid = interaction.channel_id
        
        # Ensure existence (Adopt straggler if needed)
        if hasattr(interaction.client, "handle_bar_touch") and hasattr(interaction.client, "active_bars"):
             if cid not in interaction.client.active_bars:
                 await interaction.client.handle_bar_touch(cid, interaction.message, user_id=interaction.user.id)
        
        # Update global state
        if hasattr(interaction.client, "active_bars") and cid in interaction.client.active_bars:
            interaction.client.active_bars[cid]['persisting'] = self.persisting
            
            # Sync to DB
            bar_data = interaction.client.active_bars[cid]
            memory_manager.save_bar(
                cid,
                interaction.guild_id,
                bar_data["message_id"],
                bar_data["user_id"],
                bar_data["content"],
                self.persisting,
                current_prefix=bar_data.get("current_prefix"),
                has_notification=bar_data.get("has_notification", False),
                checkmark_message_id=bar_data.get("checkmark_message_id")
            )
        
        # Check if at bottom
        is_at_bottom = False
        try:
            async for last_msg in interaction.channel.history(limit=1):
                if last_msg.id == interaction.message.id:
                    is_at_bottom = True
        except: pass

        # If enabled and NOT at bottom, drop/resend (Drop All to keep check). 
        # If disabled, OR if enabled but already at bottom, just update in place.
        if self.persisting and not is_at_bottom:
             await interaction.response.defer()
             if hasattr(interaction.client, "drop_status_bar"):
                 # When auto-dropping for persistence, we likely want to keep the checkmark if it's there.
                 await interaction.client.drop_status_bar(cid, move_bar=True, move_check=True)
        else:
             self.update_buttons()
             await interaction.response.edit_message(view=self)

    async def delete_callback(self, interaction: discord.Interaction):
        button = discord.utils.get(self.children, custom_id="bar_delete_btn")
        if not await self.check_auth(interaction, button): return
        
        # Remove from global state and DB
        if hasattr(interaction.client, "active_bars"):
            if self.channel_id in interaction.client.active_bars:
                del interaction.client.active_bars[self.channel_id]
                memory_manager.delete_bar(self.channel_id)
        
        # NEW: Remove from whitelist to clear from console
        memory_manager.remove_bar_whitelist(self.channel_id)

        # Trigger console update
        if hasattr(interaction.client, "update_console_status"):
            asyncio.create_task(interaction.client.update_console_status())
        
        await services.service.limiter.wait_for_slot("delete_message", interaction.channel_id)
        await interaction.message.delete()


# ==========================================
# WAKEUP REPORT VIEW
# ==========================================

class WakeupReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary, custom_id="wakeup_dismiss_btn")
    async def dismiss_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only Admin
        if not helpers.is_admin(interaction.user):
             await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
             return
        
        await interaction.message.delete()


# ==========================================
# CONSOLE CONTROL VIEW
# ==========================================

class ConsoleControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # 1. Create Symbols Button
        btn_symbols = discord.ui.Button(label="Symbols", url="https://discord.com/channels/411597692037496833/1302399809113821244/1363651092336083054", row=0)
        
        # 2. Capture existing items (Decorators)
        # Decorator Order: [Idle, Sleep, Reboot, Shutdown]
        existing_items = self.children[:]
        
        # 3. Insert Symbols at Index 2
        # Result: [Idle, Sleep, Symbols, Reboot, Shutdown]
        if len(existing_items) >= 2:
            existing_items.insert(2, btn_symbols)
        else:
            existing_items.append(btn_symbols) # Fallback
        
        # 4. Clear and Re-Add
        self.clear_items()
        for item in existing_items:
            self.add_item(item)

        self.update_button_styles()

    def update_button_styles(self):
        mode = memory_manager.get_server_setting("system_mode", "normal")
        
        # Idle Button
        # We need to search by custom_id because order might change or be fragile
        for child in self.children:
            if getattr(child, "custom_id", "") == "console_idle_btn":
                child.style = discord.ButtonStyle.success if mode == "idle" else discord.ButtonStyle.secondary
            elif getattr(child, "custom_id", "") == "console_sleep_btn":
                child.style = discord.ButtonStyle.success if mode == "sleep" else discord.ButtonStyle.secondary

    @discord.ui.button(emoji="💤", style=discord.ButtonStyle.secondary, custom_id="console_idle_btn", row=0)
    async def idle_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not helpers.is_admin(interaction.user):
             await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
             return
        if hasattr(interaction.client, "idle_all_bars"):
             await interaction.response.defer()
             await interaction.client.idle_all_bars()
        else:
             await interaction.response.send_message("❌ Logic missing.", ephemeral=True)

    @discord.ui.button(emoji="🛏️", style=discord.ButtonStyle.secondary, custom_id="console_sleep_btn", row=0)
    async def sleep_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not helpers.is_admin(interaction.user):
             await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
             return
        if hasattr(interaction.client, "sleep_all_bars"):
             await interaction.response.defer()
             await interaction.client.sleep_all_bars()
        else:
             await interaction.response.send_message("❌ Logic missing.", ephemeral=True)

    @discord.ui.button(emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="console_reboot_btn", row=0)
    async def reboot_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not helpers.is_admin(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        if hasattr(interaction.client, "perform_shutdown_sequence"):
            await interaction.client.perform_shutdown_sequence(interaction, restart=True)
        else:
            await interaction.response.send_message("❌ Logic missing.", ephemeral=True)

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.secondary, custom_id="console_shutdown_btn", row=0)
    async def shutdown_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not helpers.is_admin(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        if hasattr(interaction.client, "perform_shutdown_sequence"):
            await interaction.client.perform_shutdown_sequence(interaction, restart=False)
        else:
            await interaction.response.send_message("❌ Logic missing.", ephemeral=True)


# ==========================================
# VIEW
# ==========================================

class ResponseView(discord.ui.View):
    def __init__(self, original_prompt=None, user_id=None, username=None, identity_suffix=None, history_messages=None, channel_obj=None, image_data_uri=None, member_description=None, search_context=None, reply_context_str=None):
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

        # Add Debug Buttons if Debug Mode is ON
        # We check this dynamically during init
        if memory_manager.get_server_setting("debug_mode", False):
            self.add_debug_buttons()

    def add_debug_buttons(self):
        # Reboot
        btn_reboot = discord.ui.Button(label="🔄 Reboot", style=discord.ButtonStyle.danger, row=1, custom_id="debug_reboot_btn")
        btn_reboot.callback = self.debug_reboot_callback
        self.add_item(btn_reboot)
        
        # Shutdown
        btn_shutdown = discord.ui.Button(label="🛑 Shutdown", style=discord.ButtonStyle.danger, row=1, custom_id="debug_shutdown_btn")
        btn_shutdown.callback = self.debug_shutdown_callback
        self.add_item(btn_shutdown)

        # Test
        btn_test = discord.ui.Button(label="🧪 Test", style=discord.ButtonStyle.secondary, row=1, custom_id="debug_test_btn")
        btn_test.callback = self.debug_test_callback
        self.add_item(btn_test)

        # Wipe Mem
        btn_wipe = discord.ui.Button(label="🧠 Wipe Mem", style=discord.ButtonStyle.danger, row=2, custom_id="debug_wipe_mem_btn")
        btn_wipe.callback = self.debug_wipe_mem_callback
        self.add_item(btn_wipe)

        # Wipe Logs
        btn_logs = discord.ui.Button(label="🔥 Wipe Logs", style=discord.ButtonStyle.danger, row=2, custom_id="debug_wipe_logs_btn")
        btn_logs.callback = self.debug_wipe_logs_callback
        self.add_item(btn_logs)

    @discord.ui.button(label=FLAVOR_TEXT["RETRY_BUTTON"], style=discord.ButtonStyle.primary, custom_id="retry_btn", row=0)
    async def retry_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Local variables to avoid singleton pollution
        prompt = self.original_prompt
        username = self.username
        identity_suffix = self.identity_suffix
        history = self.history_messages
        channel = self.channel_obj
        image = self.image_data_uri
        desc = self.member_description
        search = self.search_context
        reply_ctx = self.reply_context_str

        # Check for lost state (Persistence Fallback)
        if prompt is None:
            state = memory_manager.get_view_state(interaction.message.id)
            if state:
                prompt = state.get('original_prompt')
                username = state.get('username')
                identity_suffix = state.get('identity_suffix')
                history = state.get('history_messages')
                channel = interaction.channel # Use current channel object
                image = state.get('image_data_uri') 
                desc = state.get('member_description')
                search = state.get('search_context')
                reply_ctx = state.get('reply_context_str')
                
                # Ensure channel has name (PartialMessageable/Thread fallback)
                if not hasattr(channel, 'name'):
                     # Try to fetch full channel if possible, or mock name
                     try:
                         if hasattr(interaction.client, 'fetch_channel'):
                             channel = await interaction.client.fetch_channel(channel.id)
                     except: pass
                     
                     if not hasattr(channel, 'name'):
                         # Create a wrapper or monkey patch for this scope if needed by services
                         # services.py uses channel_obj.id and channel_obj.name
                         class MockChannel:
                             def __init__(self, c):
                                 self.id = c.id
                                 self.name = f"channel-{c.id}"
                                 self.send = c.send
                                 self.typing = c.typing
                         channel = MockChannel(channel)

            else:
                logger.warning(f"❌ View State not found for message {interaction.message.id}")
                await interaction.response.send_message("❌ Context lost due to reboot. Cannot retry old messages.", ephemeral=True)
                return

        # 1. Disable and set status
        button.label = "Regenerating . . ."
        button.disabled = True
        await interaction.response.edit_message(view=self, content=FLAVOR_TEXT["RETRY_THINKING"])

        try:
            # 2. Call Service Logic
            new_response_text = await services.service.query_lm_studio(
                prompt, username, identity_suffix, 
                history, channel, image, desc, search, reply_ctx
            )
            
            # Use helper for consistent cleaning
            new_response_text = helpers.sanitize_llm_response(new_response_text)
            new_response_text = helpers.restore_hyperlinks(new_response_text)
            
            # 3. Cooldown Countdown (5s)
            for i in range(5, 0, -1):
                button.label = f"Wait {i}s"
                # First update commits the new text, subsequent updates just tick the timer
                if i == 5:
                    await services.service.limiter.wait_for_slot("edit_message", interaction.channel_id)
                    await interaction.edit_original_response(content=new_response_text, view=self)
                    if hasattr(interaction.client, "suppress_embeds_later"):
                        interaction.client.loop.create_task(interaction.client.suppress_embeds_later(interaction.message, delay=5))
                else:
                    await services.service.limiter.wait_for_slot("edit_message", interaction.channel_id)
                    await interaction.edit_original_response(view=self)
                await asyncio.sleep(1)
            
            # 4. Reset Button
            button.label = FLAVOR_TEXT["RETRY_BUTTON"]
            button.disabled = False
            await interaction.edit_original_response(view=self)

        except Exception as e:
            button.label = "Error!"
            await interaction.edit_original_response(content=f"❌ Error regenerating: {e}", view=self)

    @discord.ui.button(label=FLAVOR_TEXT["GOOD_BOT_BUTTON"], style=discord.ButtonStyle.success, custom_id="good_bot_btn", row=0)
    async def good_bot_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Access Client Cooldowns
        now = datetime.now().timestamp()
        last_time = getattr(interaction.client, "good_bot_cooldowns", {}).get(interaction.user.id, 0)
        
        if now - last_time < 5:
            await interaction.response.send_message(FLAVOR_TEXT["GOOD_BOT_COOLDOWN"], ephemeral=True)
            return
            
        # Valid Click
        if hasattr(interaction.client, "good_bot_cooldowns"):
             interaction.client.good_bot_cooldowns[interaction.user.id] = now
             
        count = memory_manager.increment_good_bot(interaction.user.id, interaction.user.display_name)
        
        # Update Button
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        button.label = f"Good Bot: {count}" 
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label=FLAVOR_TEXT["DELETE_BUTTON"], style=discord.ButtonStyle.danger, custom_id="delete_btn", row=0)
    async def delete_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=FLAVOR_TEXT["DELETE_MESSAGE"], view=None)
        await asyncio.sleep(3)
        try: 
            await services.service.limiter.wait_for_slot("delete_message", interaction.channel_id)
            await interaction.message.delete()
        except: pass

    @discord.ui.button(label=FLAVOR_TEXT["BUG_REPORT_BUTTON"], style=discord.ButtonStyle.secondary, custom_id="bug_report_btn", row=0)
    async def bug_report_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            BugReportModal(
                interaction.message.jump_url, 
                original_message_id=interaction.message.id, 
                channel_id=interaction.channel.id
            )
        )

    # @discord.ui.button(label=FLAVOR_TEXT["CLEAR_MEMORY_BUTTON"], style=discord.ButtonStyle.danger, custom_id="clear_mem_btn", row=0)
    # async def clear_memory_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
    #     # Update cutoff time to NOW (using interaction timestamp)
    #     interaction.client.channel_cutoff_times[self.channel_obj.id] = interaction.created_at
        
    #     memory_manager.clear_channel_memory(self.channel_obj.id, self.channel_obj.name)
    #     button.label = FLAVOR_TEXT["CLEAR_MEMORY_DONE"]
    #     button.style = discord.ButtonStyle.secondary
    #     button.disabled = True
    #     await interaction.response.edit_message(view=self)

    # --- DYNAMIC DEBUG CALLBACKS ---

    async def debug_test_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        
        await interaction.response.defer()
        try:
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

            # Create View
            view = ResponseView(
                original_prompt="TEST MESSAGE", 
                user_id=interaction.user.id, 
                username="Admin", 
                identity_suffix="", 
                history_messages=[], 
                channel_obj=interaction.channel, 
                image_data_uri=None, 
                member_description=None, 
                search_context=None, 
                reply_context_str=""
            )
            
            await interaction.followup.send(response, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")

    async def debug_reboot_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        if hasattr(interaction.client, "perform_shutdown_sequence"):
            await interaction.client.perform_shutdown_sequence(interaction, restart=True)
        else:
            await interaction.response.send_message("❌ Logic missing.", ephemeral=True)

    async def debug_shutdown_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        if hasattr(interaction.client, "perform_shutdown_sequence"):
            await interaction.client.perform_shutdown_sequence(interaction, restart=False)
        else:
            await interaction.response.send_message("❌ Logic missing.", ephemeral=True)

    async def debug_wipe_mem_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        memory_manager.wipe_all_memories()
        await interaction.response.send_message(FLAVOR_TEXT["MEMORY_WIPED"], ephemeral=True)

    async def debug_wipe_logs_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        memory_manager.wipe_all_logs()
        await interaction.response.send_message(FLAVOR_TEXT["LOGS_WIPED"], ephemeral=True)


# ==========================================
# BACKUP CONTROL VIEW
# ==========================================

class BackupControlView(discord.ui.View):
    def __init__(self, cancel_event):
        super().__init__(timeout=None)
        self.cancel_event = cancel_event
        self.cancelled = False

    @discord.ui.button(label="🛑 Cancel Backup", style=discord.ButtonStyle.danger, custom_id="backup_cancel_btn")
    async def cancel_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only authorized users can cancel
        if not helpers.is_admin(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        
        if self.cancelled:
            await interaction.response.send_message("⚠️ Cancellation already in progress...", ephemeral=True)
            return

        self.cancelled = True
        self.cancel_event.set()
        
        button.label = "Cancelling..."
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("🛑 Cancellation signal sent. Waiting for safe stop...", ephemeral=True)
