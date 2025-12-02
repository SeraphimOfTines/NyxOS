import os
import asyncio
import subprocess
import re
import time
import shutil
import logging
import dropbox
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

async def run_backup(guild_id, output_name, progress_callback=None, cancel_event=None, estimated_total_channels=0):
    """
    Runs a full backup of the specified guild, zips it, and uploads to Dropbox.
    Updates progress via the callback. Supports cancellation via cancel_event.
    """
    
    if not config.BOT_TOKEN:
        return False, "❌ Bot token is missing from configuration."
    
    if not config.DROPBOX_APP_KEY or not config.DROPBOX_REFRESH_TOKEN:
         if not config.DROPBOX_APP_KEY:
            logger.warning("Dropbox App Key missing. Upload will fail.")
    
    # 1. Setup Directories
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(base_dir, f"{output_name}Backup")
    
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    logger.info(f"Starting backup for Guild {guild_id} to {backup_dir}")
    if progress_callback:
        await progress_callback(0, config.BACKUP_FLAVOR_TEXT.get("START", "Starting..."))

    # 2. Construct Command
    # Note: We append the file format template to the output directory path
    # Tokens: %c = Channel Name, %C = Channel ID
    output_path = os.path.join(backup_dir, "%c [%C].html") 
    
    cmd = [
        EXPORTER_CLI_PATH,
        "exportguild",
        "-g", str(guild_id),
        "--output", output_path,
        "--format", "HtmlDark",
        "--media",
        "--reuse-media",
        "--include-threads", "All",
        "--parallel", "1",
        "--utc",
        "--locale", "en-US"
    ]
    
    env = os.environ.copy()
    env["DISCORD_TOKEN"] = config.BOT_TOKEN

    # 3. Execute Exporter (Background Process)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env
    )

    # Monitor Real Output
    # Regex to capture progress numbers. Allow whitespace.
    progress_pattern = re.compile(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)")
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-9:;<=>?]*[ -/]*[@-~])')
    
    # Buffer for capturing output across chunks
    output_buffer = ""
    last_update_time = 0
    last_percent = -1
    current_filename = "Initializing..."
    last_filename = ""
    current_file_size_str = "0 B"
    
    current_channel_idx = 0
    total_channels = 0
    
    start_time = time.time()
    
    # Debug Log
    debug_log_path = os.path.join(config.LOGS_DIR, "backup_debug.log")
    try:
        # Clear previous log
        open(debug_log_path, 'w').close()
    except: pass

    while True:
        # Check Cancellation
        if cancel_event and cancel_event.is_set():
            process.terminate()
            return False, "🛑 Backup Cancelled by User."

        try:
            # Read chunks instead of lines to handle \r correctly
            chunk = await asyncio.wait_for(process.stdout.read(256), timeout=0.5)
        except asyncio.TimeoutError:
            if process.returncode is not None: break # Finished
            continue

        if not chunk:
            break
        
        try:
            # Debug Write
            with open(debug_log_path, 'ab') as f:
                f.write(chunk)

            chunk_str = chunk.decode('utf-8', errors='ignore')
            # Clean ANSI codes immediately
            chunk_str = ansi_escape.sub('', chunk_str)
            output_buffer += chunk_str
            
            # Keep buffer manageable (last 1000 chars is enough for progress context)
            if len(output_buffer) > 1000:
                output_buffer = output_buffer[-1000:]

            # Check for Progress Update from Stdout
            # Regex for individual message progress: (1/100)
            prog_match = list(progress_pattern.finditer(output_buffer))
            
            # Regex for "Exporting N channel(s)..."
            # This is crucial because the individual message progress (e.g. 7%) is PER CHANNEL, not global.
            # To get global progress, we need current_channel_idx / total_channels.
            total_match = re.search(r"Exporting (\d+) channel", output_buffer)
            if total_match:
                total_channels = int(total_match.group(1))
            
            real_percent = 0
            
            # Method A: Regex from Stdout (Message count)
            # NOTE: The CLI output shown in logs is: "Channel Name ... 7%"
            # It does NOT show (1/100) for messages in the snippet I saw.
            # It seems to show a progress bar for the CURRENT channel.
            # We need to track how many channels have finished.
            
            # Logic update: 
            # 1. Detect "Fetched 'Category / Channel'" lines to know we are fetching.
            # 2. Detect "Exporting N channel(s)..." to know total.
            # 3. Detect "Channel Name ... N%" to know current channel is active.
            # 4. But the log shows the SAME channel "Veiled Podium" repeating 0% -> 7%.
            #    This means we are stuck on the first channel.
            
            # If we are parsing "Current Channel Progress", that is NOT global progress.
            # Global Progress ~= (Channels Completed / Total Channels)
            
            # We need to count how many channels have effectively "finished".
            # The log shows "Fethed 'Name'". That is the fetching phase.
            # Then "Exporting...".
            # Then "Channel Name ... N%".
            
            # If we can't easily count "Completed Channels" from the log (it clears lines with ANSI codes),
            # we MUST rely on the file count Method B for global progress.
            
            if prog_match:
                # This matches (1/100) style which might not be present in this version of CLI for channel count?
                # The log shows "Fetched 150 channel(s)." "Fetched 332 thread(s)."
                # Then "Exporting 480 channel(s)..."
                pass

            # Method B: File Count Fallback (Primary for Global Progress now)
            # The CLI output is displaying per-channel progress which is hard to map to global without counting lines.
            # File count is the most reliable "Completed Channels" metric.
            
            # We use the total_channels found in log if available, otherwise estimated.
            final_total = total_channels if total_channels > 0 else estimated_total_channels
            
            if final_total > 0:
                 # Count .html files
                 try:
                     # We need to be careful not to count the SAME file if it's being written to?
                     # Actually, .html files are created as it goes.
                     files = [name for name in os.listdir(backup_dir) if name.endswith(".html")]
                     file_count = len(files)
                     current_channel_idx = file_count
                     
                     # Calculate percent based on file count vs total channels
                     # This is "Channels Completed %"
                     real_percent = int((file_count / final_total) * 100)
                     
                     # But we can be more precise!
                     # If we have "Current Channel %" from logs (e.g. 7%), we can add that fraction?
                     # Regex for " ... N%"
                     # The log has ANSI codes: ... [38;5;8m ... [0m   7%
                     # Let's try to find the last percentage in the buffer
                     percent_match = re.findall(r'\s+(\d+)%', output_buffer)
                     if percent_match:
                         current_channel_percent = int(percent_match[-1])
                         # Add fractional progress: (file_count + (curr_pct/100)) / total
                         # Wait, file_count includes the current one usually? 
                         # If file exists, it might be partial.
                         # Let's assume file_count is "files started".
                         # So (file_count - 1 + curr_pct/100) / total?
                         # Safest is just file_count / total.
                         pass
                         
                 except: pass
            
            target_percent = real_percent
            if current_channel_idx > 0:
                # Allow drifting ahead of real percent by up to 3% to show "work is happening"
                # But snap back if real percent jumps ahead.
                
                # If we are behind real percent, catch up by 1.
                if last_percent < target_percent:
                    percent = last_percent + 1
                # If we are equal or ahead (stalled), creep forward slowly (fake progress),
                # but cap at real_percent + 4 to prevent being totally wrong.
                elif last_percent < (target_percent + 4) and last_percent < 99:
                    percent = last_percent + 1
                else:
                    percent = last_percent # Cap hit
            else:
                # If we haven't matched channel count yet, but files are growing, show some life.
                if current_file_size_str != "0 B" and current_file_size_str != "Calculating...":
                     # Start low (1%)
                     percent = max(1, last_percent)
                     
                     # Only creep up to 5% if enough time has passed (2 seconds)
                     if last_percent < 5 and (now - last_update_time > 2.0):
                         percent = last_percent + 1
                else:
                    percent = 0

            now = time.time()
            elapsed = int(now - start_time)
            elapsed_str = f"{elapsed // 60:02d}:{elapsed % 60:02d}"

            # Update if:
            # 1. Percentage changed
            # 2. It's been 3 seconds since last update (throttled)
            # 3. Filename changed (checked via FS)
            
            fs_check_needed = (now - last_update_time >= 3)
            
            if fs_check_needed:
                # Check File System for latest HTML file or Directory
                try:
                    # Scan for .html files or directories in backup_dir
                    with os.scandir(backup_dir) as it:
                        entries = [e for e in it if e.is_file() and e.name.endswith('.html') or e.is_dir()]
                        if entries:
                            # Find latest modified
                            latest_entry = max(entries, key=lambda e: e.stat().st_mtime)
                            raw_name = latest_entry.name
                            
                            # 1. Remove Suffixes
                            if raw_name.endswith("_Files"):
                                raw_name = raw_name[:-6]
                            if raw_name.endswith(".html"):
                                raw_name = raw_name[:-5]
                                
                            # 2. Remove ID [1234...] at end
                            # Match space + [digits] + end
                            raw_name = re.sub(r'\s\[\d+\]$', '', raw_name)
                            
                            # 3. Extract Channel Name (Last part after ' - ')
                            # Format: Guild - Category - Channel [ID]
                            # Or: Guild - Channel [ID]
                            parts = raw_name.split(' - ')
                            if parts:
                                current_filename = parts[-1].strip()
                            else:
                                current_filename = raw_name.strip()
                                
                            # 4. Calculate Total Directory Size (Fast)
                            # We use 'du' because recursive python walk is slow for large backups
                            try:
                                du_res = subprocess.check_output(['du', '-sb', backup_dir], stderr=subprocess.DEVNULL)
                                total_bytes = int(du_res.split()[0])
                                current_file_size_str = get_human_readable_size(total_bytes)
                            except:
                                current_file_size_str = "Calculating..."

                except OSError:
                    pass # Ignore FS errors

            should_update = (percent != last_percent) or \
                            (now - last_update_time >= 3) or \
                            (current_filename != last_filename)
            
            if should_update:
                last_percent = percent
                last_update_time = now
                last_filename = current_filename
                
                status_base = config.BACKUP_FLAVOR_TEXT.get("DOWNLOAD", "Downloading...")
                time_label = config.BACKUP_FLAVOR_TEXT.get("TIME_LABEL", "⏳ **Time Elapsed:**")
                processing_label = config.BACKUP_FLAVOR_TEXT.get("PROCESSING_LABEL", "📂 **Processing:**")
                
                channel_info = ""
                if total_channels > 0:
                    channel_info = f" (Channel {current_channel_idx}/{total_channels})"
                    
                # Update display to show Total Size next to Time
                status_msg = f"{status_base}\n{time_label} `{elapsed_str}` (`{current_file_size_str}`)\n{processing_label} `{current_filename}`{channel_info}"
                    
                if progress_callback:
                    await progress_callback(percent, status_msg)
                    
        except Exception:
            pass # Ignore decoding errors or regex fails

    await process.wait()
    
    # Double check cancellation after wait
    if cancel_event and cancel_event.is_set():
         return False, "🛑 Backup Cancelled by User."
    
    if process.returncode != 0:
        stderr = await process.stderr.read()
        err_msg = stderr.decode('utf-8')
        logger.error(f"Backup failed: {err_msg}")
        return False, f"❌ Exporter failed: {err_msg[:100]}..."

    if progress_callback:
        await progress_callback(90, config.BACKUP_FLAVOR_TEXT.get("ARCHIVE", "Archiving..."))
        
    # Check Cancellation
    if cancel_event and cancel_event.is_set(): return False, "🛑 Backup Cancelled."

    # Determine Password
    if output_name == "WM":
        archive_password = config.WM_BACKUP_PASSWORD
    else:
        archive_password = config.TEMPLE_BACKUP_PASSWORD
        
    if not archive_password:
        return False, f"❌ Password for {output_name} not configured in .env."

    # 4. Archive (7zip)
    # Date Format: MM-DD-YYYY
    date_str = datetime.now(timezone.utc).strftime("%m-%d-%Y")
    archive_name = f"{output_name}Backup-{date_str}.7z"
    archive_path = os.path.join(base_dir, archive_name)
    
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
                     
                     while f.tell() < file_size_bytes:
                         if cancel_event and cancel_event.is_set():
                             raise Exception("Cancelled by user")

                         if (file_size_bytes - f.tell()) <= 4 * 1024 * 1024:
                             dbx.files_upload_session_finish(f.read(4 * 1024 * 1024),
                                                           cursor,
                                                           commit)
                         else:
                             dbx.files_upload_session_append_v2(f.read(4 * 1024 * 1024),
                                                              cursor)
                                                              
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
    next_due_date = (datetime.now(timezone.utc) + timedelta(days=30*6)).strftime("%B %d, %Y")
    
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
