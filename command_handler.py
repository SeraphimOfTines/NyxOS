import discord
import sys
import os
import json
import asyncio
import config
import helpers
import ui
import memory_manager
import services
import logging

logger = logging.getLogger("CommandHandler")

async def handle_prefix_command(client, message):
    """
    Handles commands starting with '&'.
    Returns True if a command was processed, False otherwise.
    """
    if not message.content.startswith("&"):
        return False

    cmd = message.content.split()[0].lower()
    
    # &addchannel
    if cmd == "&addchannel":
        if not helpers.is_authorized(message.author.id) and not message.author.guild_permissions.administrator:
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        if message.channel.id in config.ALLOWED_CHANNEL_IDS:
            await message.channel.send("✅ Channel already whitelisted.")
        else:
            config.ALLOWED_CHANNEL_IDS.append(message.channel.id)
            config.save_allowed_channels(config.ALLOWED_CHANNEL_IDS)
            await message.channel.send(f"😄 I'll talk in this channel!")
        return True

    # &removechannel
    if cmd == "&removechannel":
        if not helpers.is_authorized(message.author.id) and not message.author.guild_permissions.administrator:
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        if message.channel.id in config.ALLOWED_CHANNEL_IDS:
            config.ALLOWED_CHANNEL_IDS.remove(message.channel.id)
            config.save_allowed_channels(config.ALLOWED_CHANNEL_IDS)
            await message.channel.send(f"🤐 I'll ignore this channel!")
        else:
            await message.channel.send("⚠️ Channel not in whitelist.")
        return True

    # &reboot
    if cmd == "&reboot":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
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
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
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
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        
        # Update cutoff time to NOW
        client.channel_cutoff_times[message.channel.id] = message.created_at
        
        memory_manager.clear_channel_memory(message.channel.id, message.channel.name)
        await message.channel.send(ui.FLAVOR_TEXT["CLEAR_MEMORY_DONE"])
        return True

    # &reportbug
    if cmd == "&reportbug":
        await message.channel.send(ui.FLAVOR_TEXT["REPORT_BUG_SLASH_ONLY"])
        return True

    # &goodbot
    if cmd == "&goodbot":
        leaderboard = memory_manager.get_good_bot_leaderboard()
        if not leaderboard:
            await message.channel.send(ui.FLAVOR_TEXT["NO_GOOD_BOTS"])
            return True
        total_good_bots = sum(user['count'] for user in leaderboard)
        chart_text = ui.FLAVOR_TEXT["GOOD_BOT_HEADER"]
        for i, user_data in enumerate(leaderboard[:10], 1):
            chart_text += f"**{i}.** {user_data['username']} — **{user_data['count']}**\n"
        chart_text += f"\n**Total:** {total_good_bots} Good Bots 💙"
        await message.channel.send(chart_text)
        return True

    # &synccommands
    if cmd == "&synccommands":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        await message.channel.send("🔄 Syncing commands...")
        try:
            await client.tree.sync()
            new_hash = client.get_tree_hash()
            with open(config.COMMAND_STATE_FILE, "w") as f:
                f.write(new_hash)
            await message.channel.send("✅ Commands force-synced and state updated.")
        except Exception as e:
            await message.channel.send(f"❌ Error syncing: {e}")
        return True

    # &debug
    if cmd == "&debug":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        current = memory_manager.get_server_setting("debug_mode", False)
        new_mode = not current
        memory_manager.set_server_setting("debug_mode", new_mode)
        msg = ui.FLAVOR_TEXT["DEBUG_MODE_ON"] if new_mode else ui.FLAVOR_TEXT["DEBUG_MODE_OFF"]
        await message.channel.send(msg)
        return True

    # &testmessage
    if cmd == "&testmessage":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        
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
            response = re.sub(r'\(([^)]+)\)\((https?://[^\s)]+)\)', r'[\1](\2)', response)

            view = ui.ResponseView("TEST MESSAGE", message.author.id, "Admin", "", [], message.channel, None, None, None, "")
            await message.channel.send(response, view=view)
        return True

    # &clearallmemory
    if cmd == "&clearallmemory":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        memory_manager.wipe_all_memories()
        await message.channel.send(ui.FLAVOR_TEXT["MEMORY_WIPED"])
        return True

    # &wipelogs
    if cmd == "&wipelogs":
        if not helpers.is_authorized(message.author.id):
            await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            return True
        memory_manager.wipe_all_logs()
        await message.channel.send(ui.FLAVOR_TEXT["LOGS_WIPED"])
        return True

    # &help
    if cmd == "&help":
        embed = discord.Embed(title="NyxOS Help Index", color=discord.Color.blue())
        embed.add_field(name="General Commands", value="`&killmyembeds` - Toggle auto-suppression of link embeds.\n`&goodbot` - Show the Good Bot leaderboard.\n`&reportbug` - How to report bugs.", inline=False)
        embed.add_field(name="Admin Commands", value="`&addchannel` - Whitelist channel.\n`&removechannel` - Blacklist channel.\n`&suppressembedson/off` - Toggle server-wide embed suppression.\n`&clearmemory` - Clear current channel memory.\n`&reboot` - Restart bot.\n`&shutdown` - Shutdown bot.\n`&debug` - Toggle Debug Mode.\n`&testmessage` - Send test msg (Debug).\n`&clearallmemory` - Wipe ALL memories (Debug).\n`&wipelogs` - Wipe ALL logs (Debug).\n`&synccommands` - Force sync slash commands.", inline=False)
        await message.channel.send(embed=embed)
        return True

    return False
