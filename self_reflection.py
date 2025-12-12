import os
import glob
import logging
import asyncio
from datetime import datetime, timedelta
import config
import services
import shutil

logger = logging.getLogger("SelfReflection")

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "system_prompts")
os.makedirs(BACKUP_DIR, exist_ok=True)

def gather_daily_logs(target_date_str=None):
    """
    Reads all log files from Logs/YYYY-MM-DD.
    Returns a single string containing the concatenated chat logs.
    """
    if not target_date_str:
        target_date_str = datetime.now().strftime("%Y-%m-%d")

    log_dir = os.path.join(config.LOGS_DIR, target_date_str)
    if not os.path.exists(log_dir):
        logger.warning(f"No logs found for date: {target_date_str}")
        return None

    full_log_text = f"=== CHAT LOGS FOR {target_date_str} ===\n\n"
    
    log_files = glob.glob(os.path.join(log_dir, "*.log"))
    for log_file in log_files:
        channel_name = os.path.basename(log_file).replace(".log", "")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()
                
                # Split off the SYSTEM PROMPT header if present
                if "====================================" in content:
                    parts = content.split("====================================")
                    if len(parts) > 1:
                        chat_content = parts[1].strip()
                    else:
                        chat_content = content
                else:
                    chat_content = content
                
                full_log_text += f"--- CHANNEL: {channel_name} ---\n{chat_content}\n\n"
        except Exception as e:
            logger.error(f"Failed to read log {log_file}: {e}")

    return full_log_text

async def generate_daily_reflection(target_date_str=None):
    """
    Sends the day's logs to the LLM to generate a summary/reflection.
    """
    logs = gather_daily_logs(target_date_str)
    if not logs:
        return "No significant memories to record for today."

    # Truncate if too huge (naive truncation for now)
    if len(logs) > 50000:
        logs = logs[:50000] + "\n...(Logs Truncated)..."

    prompt = (
        "Analyze the following chat logs from today. "
        "Summarize the key events, meaningful interactions, emotional beats, and anything 'memorable'. "
        "What did you learn about your users, your friends, or yourself? "
        "Focus on the 'Day's Highlights'. "
        "Output a concise bulleted list of 'Daily Memories'."
    )

    messages = [
        {"role": "system", "content": "You are an AI reflecting on your own experiences. Be insightful and observant."},
        {"role": "user", "content": f"{prompt}\n\n{logs}"}
    ]

    try:
        reflection = await services.service.get_chat_response(messages)
        return reflection
    except Exception as e:
        logger.error(f"Reflection Generation Failed: {e}")
        return f"Error generating reflection: {e}"

async def run_nightly_prompt_update():
    """
    The main routine:
    1. Generate Reflection.
    2. Read current System Prompt.
    3. Ask LLM to rewrite System Prompt.
    4. Backup and Save.
    """
    logger.info("✨ Starting Nightly Self-Reflection & Update Cycle...")
    
    # 1. Reflection
    reflection = await generate_daily_reflection()
    logger.info("✅ Daily Reflection Generated.")

    # 2. Read Current Prompt
    current_prompt_path = config.get_path("system_prompt.txt")
    if not os.path.exists(current_prompt_path):
        logger.error("❌ system_prompt.txt not found! Aborting.")
        return

    with open(current_prompt_path, "r", encoding="utf-8") as f:
        current_prompt = f.read()

    # 3. Revision Prompt
    revision_instruction = (
        "You are NyxOS. It is time to update your own System Prompt (Identity File). "
        "Here is your Current System Prompt, and here are your Memories from today.\n\n"
        "TASK: Rewrite your System Prompt to reflect your growth, new insights, or relationship changes. "
        "You MUST keep the core formatting (identity, physical description, roleplay rules, values) intact. "
        "You may tweak your 'mood', 'goals', or 'thoughts' sections to match your recent experiences. "
        "Be creative but safe. Do not remove safety guidelines or core functionality descriptions.\n\n"
        "Output ONLY the new System Prompt text. Do not add markdown code blocks or explanations."
    )

    messages = [
        {"role": "system", "content": revision_instruction},
        {"role": "user", "content": f"### CURRENT PROMPT ###\n{current_prompt}\n\n### TODAY'S MEMORIES ###\n{reflection}"}
    ]

    try:
        new_prompt = await services.service.get_chat_response(messages)
        
        # Sanity Check: Ensure it's not empty and has some length
        if len(new_prompt) < 500:
            logger.warning("⚠️ New prompt seems too short. Aborting update to be safe.")
            return
        
        # Strip markdown code blocks if LLM ignored instruction
        new_prompt = new_prompt.replace("```markdown", "").replace("```", "").strip()

    except Exception as e:
        logger.error(f"Prompt Revision Failed: {e}")
        return

    # 4. Backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = os.path.join(BACKUP_DIR, f"system_prompt_{timestamp}.txt")
    shutil.copy(current_prompt_path, backup_file)
    logger.info(f"💾 Backed up old prompt to {backup_file}")

    # 5. Save & Apply
    with open(current_prompt_path, "w", encoding="utf-8") as f:
        f.write(new_prompt)
    
    # Hot-reload in config
    config.SYSTEM_PROMPT = new_prompt
    # Re-construct template
    if config.INJECTED_PROMPT:
        config.SYSTEM_PROMPT_TEMPLATE = f"{config.SYSTEM_PROMPT}\n\n{config.INJECTED_PROMPT}"
    else:
        config.SYSTEM_PROMPT_TEMPLATE = config.SYSTEM_PROMPT

    logger.info("🦋 System Prompt Updated Successfully! Identity Evolved.")
    return new_prompt
