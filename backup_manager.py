import os
import asyncio
import subprocess
import re
import time
import shutil
import logging
import dropbox
import requests
from datetime import datetime, timedelta, timezone
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError, AuthError

import config
import services # For LLM Access
import helpers # For Sanitization

# Configure logging
logger = logging.getLogger("BackupManager")

# Path to the DiscordChatExporter CLI
EXPORTER_CLI_PATH = os.path.join(os.path.dirname(__file__), "DiscordImporter", "DiscordChatExporter.Cli")

def get_human_readable_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"


async def run_backup(target_id, output_name, target_type="guild", progress_callback=None, cancel_event=None, estimated_total_channels=0, skip_download=False, text_only=False):
    """
    Runs a full backup of the specified guild OR channel.
    If target_type is 'channel', target_id is treated as a Channel ID.
    If target_type is 'guild', target_id is treated as a Guild ID.
    If text_only is True, exports as PlainText without media.
    """
    
    if not config.BOT_TOKEN:
        return False, "❌ Bot token is missing from configuration."
    
    if not config.DROPBOX_APP_KEY or not config.DROPBOX_REFRESH_TOKEN:
         if not config.DROPBOX_APP_KEY:
            logger.warning("Dropbox App Key missing. Upload will fail.")
    
    # 1. Setup Directories
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backup_suffix = "Text" if text_only else ""
    backup_dir = os.path.join(base_dir, f"{output_name}Backup{backup_suffix}")
    
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    logger.info(f"Starting backup for {target_type} {target_id} to {backup_dir} (Text Only: {text_only})")
    if progress_callback:
        await progress_callback(0, config.BACKUP_FLAVOR_TEXT.get("START", "Starting..."))

    if not skip_download:
        # 2. Determine Channels to Export
        env = os.environ.copy()
        token_to_use = config.BACKUP_TOKEN if config.BACKUP_TOKEN else config.BOT_TOKEN
        if not token_to_use:
            return False, "❌ No valid token found for backup (BACKUP_TOKEN or BOT_TOKEN)."

        env["DISCORD_TOKEN"] = token_to_use
        channels_to_export = []

        if target_type == "channel":
            # Single Channel Mode
            channels_to_export.append((str(target_id), output_name))
        
        else:
            # Guild Mode: Fetch Channel List
            cmd_list = [
                EXPORTER_CLI_PATH,
                "channels",
                "-g", str(target_id),
                "--include-threads", "All"
            ]
            
            try:
                list_proc = await asyncio.create_subprocess_exec(
                    *cmd_list,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                stdout, stderr = await list_proc.communicate()
                
                if list_proc.returncode != 0:
                    err_msg = stderr.decode('utf-8')
                    logger.error(f"Failed to list channels: {err_msg}")
                    
                    if "not found" in err_msg.lower():
                        return False, f"❌ Guild {target_id} not found. Is the bot/user in the server?"
                    elif "401" in err_msg or "Unauthorized" in err_msg:
                        return False, "❌ Backup Token/Bot Token is invalid or unauthorized."
                    
                    return False, f"❌ Channel list failed: {err_msg[:100]}"
                    
            except Exception as e:
                logger.error(f"Failed to execute channel list command: {e}")
                return False, f"❌ Channel list command failed: {e}"

            # Parse Channels
            lines = stdout.decode('utf-8').strip().split('\n')
            for line in lines:
                if "|" in line:
                    parts = line.split("|", 1)
                    
                    # Sanitize ID: Remove any markers like '*', spaces, etc.
                    raw_id = parts[0].strip()
                    c_id = "".join(filter(str.isdigit, raw_id))
                    
                    c_name = parts[1].strip()
                    
                    if c_id:
                        channels_to_export.append((c_id, c_name))
                
        total_channels = len(channels_to_export)
        logger.info(f"Found {total_channels} channels to export.")
        
        start_time = time.time()
        
        # 3. Iterate and Export Individually
        for i, (c_id, c_name) in enumerate(channels_to_export):
            # Check Cancellation
            if cancel_event and cancel_event.is_set():
                return False, "🛑 Backup Cancelled by User."

            current_idx = i + 1
            
            # Debug Log: Start of Channel
            logger.info(f"Processing {current_idx}/{total_channels}: {c_name} ({c_id})")

            percent = int((current_idx / total_channels) * 90) # Map to 0-90% range (reserve 10% for archive/upload)
            
            # Calculate Time
            now = time.time()
            elapsed = int(now - start_time)
            hours, rem = divmod(elapsed, 3600)
            minutes, seconds = divmod(rem, 60)
            elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # Get Size
            try:
                du_res = subprocess.check_output(['du', '-sb', backup_dir], stderr=subprocess.DEVNULL)
                total_bytes = int(du_res.split()[0])
                current_file_size_str = get_human_readable_size(total_bytes)
            except:
                current_file_size_str = "Calculating..."

            # Update Status
            status_base = config.BACKUP_FLAVOR_TEXT.get("DOWNLOAD", "Downloading...")
            time_label = config.BACKUP_FLAVOR_TEXT.get("TIME_LABEL", "⏳ **Time Elapsed:**")
            processing_label = config.BACKUP_FLAVOR_TEXT.get("PROCESSING_LABEL", "📂 **Processing:**")
            
            status_msg = f"{status_base}\n{time_label} `{elapsed_str}` (`{current_file_size_str}`)\n{processing_label} `{c_name}` ({current_idx}/{total_channels})"
            
            if progress_callback:
                await progress_callback(percent, status_msg)
                
            # Run Export for Single Channel
            # Template: .../Category - Channel [ID].html (Handled by CLI automatically if directory given?)
            # Actually, if we give directory, CLI handles naming.
            # We want: "{backup_dir}/%c [%C].html"
            
            ext = ".txt" if text_only else ".html"
            output_path = os.path.join(backup_dir, f"%c [%C]{ext}")
            
            export_format = "PlainText" if text_only else "HtmlDark"
            
            export_cmd = [
                EXPORTER_CLI_PATH,
                "export",
                "-c", c_id,
                "--output", output_path,
                "--format", export_format,
                "--include-threads", "All",
                "--utc",
                "--locale", "en-US"
            ]
            
            if not text_only:
                export_cmd.extend(["--media", "--reuse-media"])
            
            # --- DEBUG LOGGING ---
            debug_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"----------------------------------------------------------------")
            logger.info(f"[DEBUG] Timestamp: {debug_timestamp}")
            logger.info(f"[DEBUG] Processing File: {c_name} (ID: {c_id})")
            logger.info(f"[DEBUG] Command Invoked: {' '.join(export_cmd)}")
            logger.info(f"----------------------------------------------------------------")
            # ---------------------

            # Run Export
            try:
                export_proc = await asyncio.create_subprocess_exec(
                    *export_cmd,
                    stdout=asyncio.subprocess.PIPE,  # Suppress output
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                
                # Create a task to handle communication (drains pipes to prevent deadlock)
                communicate_task = asyncio.create_task(export_proc.communicate())
                
                # Wait for completion or cancellation
                task_start_time = time.time()
                last_debug_log = task_start_time
                last_ui_update = task_start_time
                
                while not communicate_task.done():
                    if cancel_event and cancel_event.is_set():
                        export_proc.terminate()
                        try:
                            await asyncio.wait_for(export_proc.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            export_proc.kill()
                        
                        communicate_task.cancel()
                        try: await communicate_task
                        except: pass
                        
                        return False, "🛑 Backup Cancelled by User."
                    
                    # Debug Heartbeat (every 30s)
                    if time.time() - last_debug_log > 30:
                        duration = int(time.time() - task_start_time)
                        logger.info(f"Still exporting {c_name}... ({duration}s elapsed)")
                        last_debug_log = time.time()

                    # Live UI Update (every 3s)
                    if time.time() - last_ui_update > 3:
                        # Recalculate Time
                        now = time.time()
                        elapsed = int(now - start_time)
                        hours, rem = divmod(elapsed, 3600)
                        minutes, seconds = divmod(rem, 60)
                        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                        
                        # Recalculate Size
                        try:
                            du_res = subprocess.check_output(['du', '-sb', backup_dir], stderr=subprocess.DEVNULL)
                            total_bytes = int(du_res.split()[0])
                            current_file_size_str = get_human_readable_size(total_bytes)
                        except:
                            current_file_size_str = "Calculating..."

                        # Re-construct Status Msg
                        status_msg = f"{status_base}\n{time_label} `{elapsed_str}` (`{current_file_size_str}`)\n{processing_label} `{c_name}` ({current_idx}/{total_channels})"
                        
                        if progress_callback:
                            try: await progress_callback(percent, status_msg)
                            except: pass
                        
                        last_ui_update = time.time()

                    # Wait briefly for task completion
                    done, pending = await asyncio.wait([communicate_task], timeout=1.0)
                    if done:
                        break

                # Get result
                _, stderr_data = await communicate_task
                
                if export_proc.returncode != 0:
                    err_msg = stderr_data.decode('utf-8')
                    if "429" in err_msg or "Too Many Requests" in err_msg:
                        logger.warning(f"Rate limit hit on {c_name}. Sleeping extra.")
                        await asyncio.sleep(10) 
                    elif "403" in err_msg or "404" in err_msg:
                        logger.warning(f"Access denied or missing: {c_name}. Skipping.")
                    else:
                        logger.warning(f"Export failed for {c_name}: {err_msg[:100]}")
                else:
                    logger.info(f"Finished export for {c_name}")
                        
            except Exception as e:
                logger.error(f"Export exception for {c_name}: {e}")

            # RATE LIMIT PAUSE
            # User requested pause. 6 seconds seems safe if hitting limits every 5s.
            pause_duration = 8
            logger.info(f"[DEBUG] Pausing for {pause_duration} seconds before next job...")
            start_pause = time.time()
            await asyncio.sleep(pause_duration)
            actual_pause = time.time() - start_pause
            logger.info(f"[DEBUG] Resumed after {actual_pause:.2f} seconds.") 
    else:
        logger.info("SKIPPING DOWNLOAD STEP (Archive/Upload Only Mode)") 

    # 4. Archive (7zip)
    if progress_callback:
        await progress_callback(90, config.BACKUP_FLAVOR_TEXT.get("ARCHIVE", "Archiving..."))

    # Determine Password
    if output_name == "WM":
        archive_password = config.WM_BACKUP_PASSWORD
    else:
        archive_password = config.TEMPLE_BACKUP_PASSWORD
        
    if not archive_password:
        return False, f"❌ Password for {output_name} not configured in .env."

    # Date Format: MM-DD-YYYY
    date_str = datetime.now(timezone.utc).strftime("%m-%d-%Y")
    
    # Text suffix for archive name
    name_suffix = "Text" if text_only else ""
    archive_name = f"{output_name}Backup{name_suffix}-{date_str}.7z"
    archive_path = os.path.join(base_dir, archive_name)
    
    # Remove existing archive if any
    if os.path.exists(archive_path):
        os.remove(archive_path)

    zip_cmd = [
        "7z", "a",
        f"-p{archive_password}",
        "-mhe=on",
        archive_path,
        backup_dir
    ]
    
    zip_proc = await asyncio.create_subprocess_exec(
        *zip_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Wait for zip with cancellation check
    while zip_proc.returncode is None:
        if cancel_event and cancel_event.is_set():
            zip_proc.terminate()
            return False, "🛑 Backup Cancelled during archiving."
        try:
            await asyncio.wait_for(zip_proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
    
    if zip_proc.returncode != 0:
        return False, "❌ Archiving failed."
        
    # Calculate File Size
    file_size_bytes = os.path.getsize(archive_path)
    readable_size = get_human_readable_size(file_size_bytes)

    if progress_callback:
        await progress_callback(95, config.BACKUP_FLAVOR_TEXT.get("UPLOAD", "Uploading..."))

    # Check Cancellation
    if cancel_event and cancel_event.is_set(): 
        os.remove(archive_path)
        return False, "🛑 Backup Cancelled."

    url = "Link unavailable"
    
    # 5. Upload to Dropbox
    try:
        if config.DROPBOX_APP_KEY and config.DROPBOX_REFRESH_TOKEN:
             dbx = dropbox.Dropbox(
                 app_key=config.DROPBOX_APP_KEY,
                 app_secret=config.DROPBOX_APP_SECRET,
                 oauth2_refresh_token=config.DROPBOX_REFRESH_TOKEN
             )
             
             dropbox_path = f"/{archive_name}"
             
             with open(archive_path, "rb") as f:
                 if file_size_bytes <= 150 * 1024 * 1024:
                     dbx.files_upload(f.read(), dropbox_path, mode=WriteMode('overwrite'))
                 else:
                     # Chunked upload with cancellation support
                     upload_session_start_result = dbx.files_upload_session_start(f.read(4 * 1024 * 1024))
                     cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id,
                                                              offset=f.tell())
                     commit = dropbox.files.CommitInfo(path=dropbox_path)
                     
                     last_upload_ui_update = 0
                     last_log_pct = -1

                     while f.tell() < file_size_bytes:
                         if cancel_event and cancel_event.is_set():
                             raise Exception("Cancelled by user")
                        
                         # Progress Update
                         current_pos = f.tell()
                         now = time.time()
                         if now - last_upload_ui_update > 4:
                             pct = int((current_pos / file_size_bytes) * 100)
                             uploaded_str = get_human_readable_size(current_pos)
                             status_msg = f"Uploading... {uploaded_str} / {readable_size}"
                             
                             if progress_callback:
                                 await progress_callback(pct, status_msg)
                                 
                             if pct >= last_log_pct + 10:
                                 logger.info(f"Uploading: {pct}% ({uploaded_str}/{readable_size})")
                                 last_log_pct = pct
                                 
                             last_upload_ui_update = now

                         chunk = f.read(4 * 1024 * 1024)
                         
                         # Retry logic for chunk upload
                         for attempt in range(3):
                             try:
                                 if f.tell() == file_size_bytes:
                                     dbx.files_upload_session_finish(chunk, cursor, commit)
                                 else:
                                     dbx.files_upload_session_append_v2(chunk, cursor)
                                     cursor.offset += len(chunk)
                                 break # Success
                             except (requests.exceptions.RequestException, Exception) as e:
                                 # Check for specific errors if needed, but general retry for network/socket issues is safe here
                                 # as long as we don't advance the cursor prematurely (which we don't, as cursor.offset is only updated on success).
                                 if attempt == 2: 
                                     logger.error(f"Upload failed after 3 attempts. Final error: {e}")
                                     raise e
                                 
                                 logger.warning(f"Dropbox upload failed (Attempt {attempt+1}/3). Retrying in 5s... Error: {e}")
                                 await asyncio.sleep(5)
                                                              
             try:
                 shared_link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_path)
                 url = shared_link_metadata.url
             except dropbox.exceptions.ApiError as e:
                 if e.error.is_shared_link_already_exists():
                     links = dbx.sharing_list_shared_links(path=dropbox_path).links
                     url = links[0].url if links else "Link Error"
                 else:
                     url = "Could not generate link."
                     
             os.remove(archive_path)
             
        else:
             url = f"Local File: `{archive_name}`"

    except Exception as e:
        if "Cancelled" in str(e):
            return False, "🛑 Backup Cancelled during upload."
        logger.error(f"Dropbox upload failed: {e}")
        return False, f"❌ Upload failed: {e}"
        
    # 6. Finalize & Template
    if progress_callback:
        await progress_callback(99, config.BACKUP_FLAVOR_TEXT.get("FINISH", "Finishing..."))

    # Calculate Next Due (6 Months)
    future_date = datetime.now(timezone.utc) + timedelta(days=30*6)
    next_due_timestamp = int(future_date.timestamp())
    next_due_date = f"<t:{next_due_timestamp}:R>"
    
    # Get LLM Message
    llm_message = "Backup complete!"
    try:
        # Select Prompt based on Target
        if output_name == "WM":
            target_prompt = config.WM_BACKUP_PROMPT
        else:
            # Default to Temple/Generic prompt for Temple, Shrine, or others
            target_prompt = config.TEMPLE_BACKUP_PROMPT

        # Construct Full System Prompt Stack
        full_system_prompt = config.SYSTEM_PROMPT
        
        # Strip Date/Time from prompt for Backups to prevent hallucinations
        full_system_prompt = full_system_prompt.replace("Right now its {{CURRENT_WEEKDAY}}, {{CURRENT_DATETIME}}.", "")
        
        if config.INJECTED_PROMPT:
            full_system_prompt += f"\n\n{config.INJECTED_PROMPT}"
            
        messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": f"{target_prompt}\n\nContext: Backup Size: {readable_size}, Archive: {archive_name}"}
        ]
        llm_message = await services.service.get_chat_response(messages)
        
        # SANITIZATION & FORMATTING
        llm_message = helpers.sanitize_llm_response(llm_message)
        llm_message = llm_message.replace("{{USER_NAME}}", "Admins") # Generic replace
        
    except Exception as e:
        logger.error(f"LLM Generation failed: {e}")
        llm_message = "Backup successful! (LLM comment failed)"

    # Get Admin Ping
    admin_ping = config.ADMIN_PINGS.get(output_name, "")

    # Get Template based on target
    if isinstance(config.BACKUP_COMPLETION_TEMPLATE, dict):
        template = config.BACKUP_COMPLETION_TEMPLATE.get(output_name, config.BACKUP_COMPLETION_TEMPLATE.get("Default"))
    else:
        template = config.BACKUP_COMPLETION_TEMPLATE # Fallback if still string

    # Format Template
    final_message = template.format(
        size=readable_size,
        password=archive_password,
        next_due=next_due_date,
        llm_message=llm_message,
        link=url,
        admin_ping=admin_ping
    )

    return True, final_message
