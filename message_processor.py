import discord
import re
import asyncio
import base64
import logging
import config
import helpers
import services
import memory_manager
import ui

logger = logging.getLogger("MessageProcessor")

async def process_message(client, message):
    """
    Handles the main message processing logic:
    - Admin updates
    - Proxy checks
    - Trigger detection
    - Good Bot logic
    - LLM Query & Response
    """
    
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

    # --- PROXY/WEBHOOK CHECKS ---
    if message.webhook_id is None:
        tags = await services.service.get_system_proxy_tags(config.MY_SYSTEM_ID)
        if helpers.matches_proxy_tag(message.content, tags): return
        
        # Ghost Check
        await asyncio.sleep(2.0)
        try:
            await message.channel.fetch_message(message.id)
            async for recent in message.channel.history(limit=15):
                if recent.webhook_id is not None:
                        diff = (recent.created_at - message.created_at).total_seconds()
                        if abs(diff) < 3.0: return
        except (discord.NotFound, discord.HTTPException): 
            # If fetch fails, it might be deleted (proxied).
            # But for TESTS, we mock fetch_message.
            # If mock raises NotFound, we return.
            pass

    # --- RESPONSE TRIGGER ---
    should_respond = False
    if client.user in message.mentions: should_respond = True
    if not should_respond:
        if message.role_mentions:
            for role in message.role_mentions:
                if role.id in config.BOT_ROLE_IDS: should_respond = True; break
        if not should_respond:
            for rid in config.BOT_ROLE_IDS:
                if f"<@&{rid}>".format(rid) in message.content: should_respond = True; break
    
    # Check Reply (Robust)
    target_message_id = None
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

    # --- GOOD BOT CHECK ---
    if re.search(r'\bgood\s*bot\b', message.content, re.IGNORECASE):
        is_ping = client.user in message.mentions
        # If replying to me OR pinging me
        if is_ping or target_message_id:
            if not target_message_id:
                target_message_id = client.last_bot_message_id.get(message.channel.id)
            
            # Determine sender ID
            sender_id = message.author.id
            # If webhook, we might need better ID resolution, but standard logic uses author.id unless proxied.
            # Let's resolve identity properly first for the "Good Bot" check
            
            # Identity Logic (Partial duplication for Good Bot accurate naming)
            real_name = message.author.display_name
            pk_tag = None
            is_pk_proxy = False
            system_name = None
            
            if message.webhook_id:
                pk_name, pk_sys_id, pk_sys_name, pk_tag_val, pk_sender, _ = await services.service.get_pk_message_data(message.id)
                if pk_name:
                    real_name = pk_name
                    pk_tag = pk_tag_val
                    if pk_sender: sender_id = pk_sender
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
        allowed_channels = memory_manager.get_allowed_channels()
        # GLOBAL CHAT CHECK
        # If Global Chat is enabled, bypass whitelist.
        global_enabled = memory_manager.get_server_setting("global_chat_enabled")
        is_whitelisted = message.channel.id in allowed_channels
        
        # Logic: Respond IF (Whitelisted) OR (Global Enabled).
        # BUT we also want to allow "Summoning" via ping in non-whitelisted channels even if Global is OFF?
        # The README says "Only Admins and Special roles".
        # But currently `should_respond` is true if pinged.
        
        # Let's stick to:
        # If Pinged -> Respond (Bypass Whitelist) ?
        # Tests expect Ping to Bypass Whitelist.
        
        can_chat = is_whitelisted or global_enabled or (client.user in message.mentions)
        
        # Also checking roles mentions bypass?
        if not can_chat and message.role_mentions:
             for role in message.role_mentions:
                if role.id in config.BOT_ROLE_IDS: can_chat = True; break
        
        if not can_chat: return

        if message.channel.id not in client.boot_cleared_channels:
            logger.info(f"🧹 First message in #{message.channel.name} since boot. Wiping memory.")
            memory_manager.clear_channel_memory(message.channel.id, message.channel.name)
            client.boot_cleared_channels.add(message.channel.id)

        client.processing_locks.add(message.id)
        logger.info(f"Processing Message from {message.author.name} (ID: {message.id})")

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
                    sender_id = pk_sender
                    system_id = pk_sys_id
                    member_description = pk_desc
            else:
                sender_id = message.author.id
                user_sys_data = await services.service.get_pk_user_data(sender_id)
                if user_sys_data: 
                    system_tag = user_sys_data['tag']
                    system_id = user_sys_data['system_id']

            clean_name = helpers.clean_name_logic(real_name, system_tag)
            # Identity Suffix uses new Config logic
            identity_suffix = helpers.get_identity_suffix(sender_id, system_id, clean_name, services.service.my_system_members)

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

            # Query LLM
            response_text = await services.service.query_lm_studio(
                clean_prompt, clean_name, identity_suffix, history_messages, 
                message.channel, image_data_uri, member_description, search_context, current_reply_context
            )
            
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
                    client.loop.create_task(client.suppress_embeds_later(sent_message, delay=5))

            except discord.HTTPException as e:
                logger.error(f"DEBUG: Failed to reply: {e}")