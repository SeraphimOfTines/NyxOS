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
    "DELETE_BUTTON": "🗑️ Delete",
    "DELETE_MESSAGE": "# <a:SeraphCometFire:1326369374755491881> Message deleted <a:SeraphCometFire:1326369374755491881>",
    "GOOD_BOT_BUTTON": "Good Bot! 💙",
    "GOOD_BOT_COOLDOWN": "🤚🏻 Fucking CHILL! 😒",
    "BUG_REPORT_BUTTON": "🐛",
    "BUG_REPORT_THANKS": "✅ Thanks for the help! You're the best! 😉",
    "CLEAR_MEMORY_BUTTON": "🧠 Clear Memory",
    "CLEAR_MEMORY_DONE": "🤯 Memory Cleared",
    "NOT_AUTHORIZED": "🤨 You're not my admin. Shoo!",
    "NO_GOOD_BOTS": "No one has called me a good bot yet! <:SeraphCryCute:1402341656698687540>",
    "GOOD_BOT_HEADER": "# 💙 I'm such a good bot! 💙\n\n",
    "STARTUP_MESSAGE": "# <a:SATVRNCommand:1301834555086602240> I'm back online! Hi!",
    "REBOOT_MESSAGE": "# <a:Thinking:1322962569300017214> Rebooting . . .",
    "SHUTDOWN_MESSAGE": "# <a:Sleeping:1312772391759249410> Shutting down . . . Goodnight!",
    "CRASH_MESSAGE": "# <a:SeraphBurningFuck:1304766240648204298> I just crashed! <a:SeraphCryHandsSnap:1297004800117837906>",
    "REPORT_BUG_SLASH_ONLY": "ℹ️ Please use the `/reportbug` slash command to submit a report.",
    "EMBED_SUPPRESSION_ENABLED": "🔇 Hyperlink embeds will now be auto-suppressed for you.",
    "EMBED_SUPPRESSION_DISABLED": "🔊 Hyperlink embeds will no longer be suppressed for you.",
    "GLOBAL_SUPPRESSION_ON": "✅ Server-wide embed suppression feature is now **ENABLED**.",
    "GLOBAL_SUPPRESSION_OFF": "❌ Server-wide embed suppression feature is now **DISABLED**.",
    "DEBUG_MODE_ON": "🔧 Debug Mode **ENABLED**.",
    "DEBUG_MODE_OFF": "🔧 Debug Mode **DISABLED**.",
    "TEST_MESSAGE": "🧪 This is a test message!",
    "MEMORY_WIPED": "🧹🧹 All memory files have been wiped!",
    "LOGS_WIPED": "🔥 All log files have been wiped!",
    "GLOBAL_CHAT_ENABLED": "🌍 Global Chat Mode **ENABLED**. I will now respond in all channels!",
    "GLOBAL_CHAT_DISABLED": "🔒 Global Chat Mode **DISABLED**. I will only respond in whitelisted channels.",
    "GOOD_BOT_REACTION": "💙",
    "WAKE_WORD_REACTION": "<a:Thinking:1322962569300017214>",
    "BAR_DROP": "⬇️ Drop",
    "BAR_DROP_ALL": "⏬ Drop All",
    "BAR_DELETE": "🗑️ Delete",
    "BAR_PERSIST_OFF": "🔁 Persist: OFF",
    "BAR_PERSIST_ON": "✅ Persist: ON",
    "CHECKMARK_EMOJI": "<a:AllCaughtUp:1289323947082387526>",
}

BAR_PREFIX_EMOJIS = [
    "<a:WatchingOccasionally:1301837550159269888>",
    "<a:WatchingClosely:1301838354832425010>",
    "<a:NotWatching:1301840196966285322>",
    "<a:Thinking:1322962569300017214>", # /thinking
    "<a:Sleeping:1312772391759249410>", # /sleeping (from shutdown msg)
    "<a:Reading:1378593438265770034>",
    "<a:Backlogging:1290067150861500588>", 
    "<a:Typing:1223747307657232405>",
    "<a:Processing:1223643308140793969>",
    "<a:Pausing:1385258657532481597>",
    "<a:Angel:000000000000000000>",
    "<a:DarkAngel:000000000000000000>",
    "<a:BRB:000000000000000000>"
]

ANGEL_CONTENT = "<a:SacredMagicStrong:1316971256830103583><a:SeraphWingLeft:1297050718754312192><a:SacredEyeLuminara:1296698905744113715><a:SeraphWingRight:1297051921651073055><a:SacredMagicStrong:1316971256830103583>\n<a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466><a:SacredWind:1296975869566259396><a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466>"
DARK_ANGEL_CONTENT = "<a:SacredMagicStrong:1316971256830103583><a:SeraphWingLeft:1297050718754312192><a:SacredEyeYami:1418478480336879716><a:SeraphWingRight:1297051921651073055><a:SacredMagicStrong:1316971256830103583>\n<a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466><a:SacredWind:1296975869566259396><a:HyperRingPresence:1303962112317587466><a:HyperRingPresence:1303962112317587466>"

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
            await interaction.response.send_message(FLAVOR_TEXT["BUG_REPORT_THANKS"], ephemeral=True)
            
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
# STATUS BAR VIEW
# ==========================================

class StatusBarView(discord.ui.View):
    def __init__(self, content, original_user_id, channel_id, persisting=False):
        super().__init__(timeout=None)
        self.content = content
        self.original_user_id = original_user_id
        self.channel_id = channel_id
        self.persisting = persisting
        
        # Update persist button state on init
        self.update_buttons()

    def update_buttons(self):
        for child in self.children:
            if getattr(child, "custom_id", "") == "bar_persist_btn":
                child.label = FLAVOR_TEXT["BAR_PERSIST_ON"] if self.persisting else FLAVOR_TEXT["BAR_PERSIST_OFF"]
                child.style = discord.ButtonStyle.success if self.persisting else discord.ButtonStyle.secondary

    async def check_auth(self, interaction, button):
        # Only Original User or Admin
        if interaction.user.id == self.original_user_id or helpers.is_authorized(interaction.user):
            return True
        
        # Unauthorized Animation
        original_label = button.label
        button.label = "Nope!"
        await interaction.response.edit_message(view=self)
        await asyncio.sleep(1)
        button.label = original_label
        try: await interaction.edit_original_response(view=self)
        except: pass
        return False

    @discord.ui.button(label=FLAVOR_TEXT["BAR_DROP"], style=discord.ButtonStyle.primary, custom_id="bar_drop_btn")
    async def drop_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_auth(interaction, button): return
        
        await interaction.response.defer()
        if hasattr(interaction.client, "drop_status_bar"):
            await interaction.client.drop_status_bar(self.channel_id, move_check=False)
        else:
            await interaction.followup.send("❌ Error: Functionality not found.", ephemeral=True)

    @discord.ui.button(label=FLAVOR_TEXT["BAR_DROP_ALL"], style=discord.ButtonStyle.primary, custom_id="bar_drop_all_btn")
    async def drop_all_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_auth(interaction, button): return
        
        await interaction.response.defer()
        if hasattr(interaction.client, "drop_status_bar"):
            await interaction.client.drop_status_bar(self.channel_id, move_check=True)
        else:
            await interaction.followup.send("❌ Error: Functionality not found.", ephemeral=True)

    @discord.ui.button(label=FLAVOR_TEXT["BAR_DELETE"], style=discord.ButtonStyle.danger, custom_id="bar_delete_btn")
    async def delete_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_auth(interaction, button): return
        
        # Remove from global state and DB
        if hasattr(interaction.client, "active_bars"):
            if self.channel_id in interaction.client.active_bars:
                del interaction.client.active_bars[self.channel_id]
                memory_manager.delete_bar(self.channel_id)
        
        await interaction.message.delete()

    @discord.ui.button(label=FLAVOR_TEXT["BAR_PERSIST_OFF"], style=discord.ButtonStyle.secondary, custom_id="bar_persist_btn")
    async def persist_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_auth(interaction, button): return
        
        self.persisting = not self.persisting
        
        # Update global state
        if hasattr(interaction.client, "active_bars") and self.channel_id in interaction.client.active_bars:
            interaction.client.active_bars[self.channel_id]['persisting'] = self.persisting
            
            # Sync to DB (Full save needed as persisting is a column)
            bar_data = interaction.client.active_bars[self.channel_id]
            memory_manager.save_bar(
                self.channel_id,
                interaction.guild_id,
                bar_data["message_id"],
                bar_data["user_id"],
                bar_data["content"],
                self.persisting
            )
        
        # If enabled, immediately drop (send new copy) to activate behavior
        if self.persisting:
             await interaction.response.defer()
             if hasattr(interaction.client, "drop_status_bar"):
                 await interaction.client.drop_status_bar(self.channel_id, move_check=False)
        else:
             self.update_buttons()
             await interaction.response.edit_message(view=self)


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
            else:
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
                    await interaction.edit_original_response(content=new_response_text, view=self)
                    if hasattr(interaction.client, "suppress_embeds_later"):
                        interaction.client.loop.create_task(interaction.client.suppress_embeds_later(interaction.message, delay=5))
                else:
                    await interaction.edit_original_response(view=self)
                await asyncio.sleep(1)
            
            # 4. Reset Button
            button.label = FLAVOR_TEXT["RETRY_BUTTON"]
            button.disabled = False
            await interaction.edit_original_response(view=self)

        except Exception as e:
            button.label = "Error!"
            await interaction.edit_original_response(content=f"❌ Error regenerating: {e}", view=self)

    @discord.ui.button(label=FLAVOR_TEXT["DELETE_BUTTON"], style=discord.ButtonStyle.danger, custom_id="delete_btn", row=0)
    async def delete_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=FLAVOR_TEXT["DELETE_MESSAGE"], view=None)
        await asyncio.sleep(3)
        try: await interaction.message.delete()
        except: pass

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
        await interaction.response.send_message(FLAVOR_TEXT["REBOOT_MESSAGE"])
        
        meta = {"channel_id": interaction.channel_id}
        try:
            with open(config.RESTART_META_FILE, "w") as f:
                json.dump(meta, f)
                f.flush()
                os.fsync(f.fileno())
        except: pass
        await interaction.client.close()
        python = sys.executable
        os.execl(python, python, *sys.argv)

    async def debug_shutdown_callback(self, interaction: discord.Interaction):
        if not helpers.is_authorized(interaction.user):
            await interaction.response.send_message(FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            return
        await interaction.response.send_message(FLAVOR_TEXT["SHUTDOWN_MESSAGE"])
        try:
            with open(config.SHUTDOWN_FLAG_FILE, "w") as f: f.write("shutdown")
        except: pass
        await interaction.client.close()
        sys.exit(0)

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
