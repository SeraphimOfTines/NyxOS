import os
import glob
import logging
import asyncio
import json
from datetime import datetime, timedelta
import config
import services
import shutil

logger = logging.getLogger("SelfReflection")

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "system_prompts")
os.makedirs(BACKUP_DIR, exist_ok=True)

def gather_logs_for_date(date_obj):
    """
    Reads all log files for a specific date (YYYY-MM-DD).
    Returns a single string containing the concatenated chat logs.
    """
    date_str = date_obj.strftime("%Y-%m-%d")
    log_dir = os.path.join(config.LOGS_DIR, date_str)
    
    if not os.path.exists(log_dir):
        return None

    full_log_text = f"=== CHAT LOGS FOR {date_str} ===\n\n"
    log_files = glob.glob(os.path.join(log_dir, "*.log"))
    
    if not log_files:
        return None
        
    for log_file in log_files:
        channel_name = os.path.basename(log_file).replace(".log", "")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()
                if "====================================" in content:
                    parts = content.split("====================================")
                    chat_content = parts[1].strip() if len(parts) > 1 else content
                else:
                    chat_content = content
                full_log_text += f"--- CHANNEL: {channel_name} ---\n{chat_content}\n\n"
        except Exception as e:
            logger.error(f"Failed to read log {log_file}: {e}")

    return full_log_text

async def generate_reflection_for_date(date_obj):
    """
    Generates reflection for a specific date.
    """
    logs = gather_logs_for_date(date_obj)
    if not logs:
        return None # No logs, no reflection needed

    if len(logs) > 60000:
        logs = logs[:60000] + "\n...(Logs Truncated)..."

    prompt = (
        f"Analyze the following chat logs from {date_obj.strftime('%Y-%m-%d')}. "
        "Summarize the key events, meaningful interactions, emotional beats, and anything 'memorable'. "
        "What did you learn about your users, your friends, or yourself? "
        "Focus on the Highlights. "
        "Output a concise bulleted list of 'Memories'."
    )

    messages = [
        {"role": "system", "content": "You are an AI reflecting on your own experiences. Be insightful and observant."},
        {"role": "user", "content": f"{prompt}\n\n{logs}"}
    ]

    try:
        reflection = await services.service.get_chat_response(messages)
        return reflection
    except Exception as e:
        logger.error(f"Reflection Generation Failed for {date_obj}: {e}")
        return None

async def update_prompt_with_reflection(reflection, date_str):
    """
    Applies the reflection to the System Prompt and Backs it up.
    """
    # 1. Read Current Prompt
    current_prompt_path = config.get_path("system_prompt.txt")
    if not os.path.exists(current_prompt_path):
        logger.error("❌ system_prompt.txt not found! Aborting.")
        return False

    with open(current_prompt_path, "r", encoding="utf-8") as f:
        current_prompt = f.read()

    # 2. Revision Prompt
    revision_instruction = (
        "You are NyxOS. It is time to update your own System Prompt (Identity File). "
        "Here is your Current System Prompt, and here are your recent Memories.\n\n"
        "TASK: Rewrite your System Prompt to reflect your growth, new insights, or relationship changes. "
        "You MUST keep the core formatting (identity, physical description, roleplay rules, values) intact. "
        "You may tweak your 'mood', 'goals', or 'thoughts' sections to match your recent experiences. "
        "Be creative but safe. Do not remove safety guidelines or core functionality descriptions.\n\n"
        "Output ONLY the new System Prompt text. Do not add markdown code blocks or explanations."
    )

    # --- EMOTIONAL INJECTION ---
    emotional_stats = ""
    if hasattr(services.service, 'emotional_core'):
         ec = services.service.emotional_core
         stats = ec.state["stats"]
         stats_str = ", ".join([f"{k}: {v}" for k, v in stats.items()])
         narrative = ec.get_narrative_prompt()
         emotional_stats = f"\n\n### CURRENT EMOTIONAL STATE ###\nStats: {stats_str}\nNarrative: {narrative}"

    messages = [
        {"role": "system", "content": revision_instruction},
        {"role": "user", "content": f"### CURRENT PROMPT ###\n{current_prompt}\n\n### MEMORIES FROM {date_str} ###\n{reflection}{emotional_stats}"}
    ]

    try:
        new_prompt = await services.service.get_chat_response(messages)
        
        if len(new_prompt) < 500:
            logger.warning("⚠️ New prompt seems too short. Aborting update to be safe.")
            return False
        
        new_prompt = new_prompt.replace("```markdown", "").replace("```", "").strip()

    except Exception as e:
        logger.error(f"Prompt Revision Failed: {e}")
        return False

    # 3. Backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = os.path.join(BACKUP_DIR, f"system_prompt_{date_str}_applied_{timestamp}.txt")
    try:
        shutil.copy(current_prompt_path, backup_file)
        logger.info(f"💾 Backed up old prompt to {backup_file}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")

    # 4. Save & Apply
    try:
        with open(current_prompt_path, "w", encoding="utf-8") as f:
            f.write(new_prompt)
        
        config.SYSTEM_PROMPT = new_prompt
        if config.INJECTED_PROMPT:
            config.SYSTEM_PROMPT_TEMPLATE = f"{config.SYSTEM_PROMPT}\n\n{config.INJECTED_PROMPT}"
        else:
            config.SYSTEM_PROMPT_TEMPLATE = config.SYSTEM_PROMPT

        logger.info(f"🦋 System Prompt Updated Successfully using {date_str} memories.")
        return True

    except Exception as e:
        logger.error(f"Failed to save new prompt: {e}")
        return False

async def process_missed_days():
    """
    Iterates through all days since last run, processing them sequentially.
    Updates state after each successful day.
    """
    logger.info("✨ Starting Catch-Up Reflection Cycle...")
    
    # 1. Load State
    last_run = datetime.now() - timedelta(days=1)
    if os.path.exists(config.REFLECTION_STATE_FILE):
        try:
            with open(config.REFLECTION_STATE_FILE, "r") as f:
                data = json.load(f)
                last_run_str = data.get("last_run")
                if last_run_str:
                    last_run = datetime.fromisoformat(last_run_str)
        except: pass

    # 2. Determine Range
    start_date = last_run.date()
    # If the last run was effectively "end of day" (completed), start from the next day.
    # We use 23:00 as a safe threshold for "nightly run complete".
    if last_run.hour >= 23:
        start_date += timedelta(days=1)
        
    end_date = datetime.now().date()
    
    processed_count = 0
    current_date = start_date
    
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip today if it's not late enough? 
        # User said "automatically trigger at midnight".
        # If running manually (mid-day), we include today "so far".
        
        logger.info(f"📅 Checking logs for: {date_str}")
        
        # Generate
        reflection = await generate_reflection_for_date(current_date)
        
        if reflection:
            logger.info(f"✅ Generated reflection for {date_str}")
            success = await update_prompt_with_reflection(reflection, date_str)
            if success:
                processed_count += 1
                # Update State to THIS day (approximate time end of day)
                # We set last_run to the next midnight relative to this date, or just now?
                # Ideally, we set it to "completed this date".
                # But if we crash, we want to resume.
                # Let's set it to the END of that date (23:59:59) so next run starts next day.
                # Unless it's TODAY. Then set to NOW.
                
                if current_date == end_date:
                    new_mark = datetime.now()
                else:
                    new_mark = datetime.combine(current_date, datetime.max.time())
                
                try:
                    with open(config.REFLECTION_STATE_FILE, "w") as f:
                        json.dump({"last_run": new_mark.isoformat()}, f)
                except: pass
        else:
            logger.info(f"⚪ No logs or reflection for {date_str}. Skipping.")
        
        current_date += timedelta(days=1)

    return processed_count

# --- Legacy/Debug Wrapper ---
async def generate_daily_reflection(target_date_str=None):
    if not target_date_str:
        target_date_str = datetime.now().strftime("%Y-%m-%d")
    dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    return await generate_reflection_for_date(dt)

async def run_nightly_prompt_update():
    """Wrapper to run the full catch-up process."""
    return await process_missed_days()
