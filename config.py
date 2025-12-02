import os
import json
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_path(filename):
    return os.path.join(BASE_DIR, filename)

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================

# File/Directory Paths
MEMORY_DIR = get_path("Memory")
LOGS_DIR = get_path("Logs")
RESTART_META_FILE = get_path("restart_metadata.json")
DATABASE_FILE = get_path("nyxos.db")
BUFFER_FILE = get_path("buffer.txt")
HEARTBEAT_FILE = get_path("heartbeat.txt")
SHUTDOWN_FLAG_FILE = get_path("shutdown.flag")
COMMAND_STATE_FILE = get_path("command_state.hash")

# API Endpoints
KAGI_SEARCH_URL = "https://kagi.com/api/v0/search"

# PluralKit Configuration
USE_LOCAL_PLURALKIT = False
LOCAL_PLURALKIT_API_URL = "http://localhost:5000/v2"
PLURALKIT_DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres"

# --- SECRET LOADING ---
# Secrets are loaded from .env or config.txt

BOT_TOKEN = os.getenv("BOT_TOKEN")
KAGI_API_TOKEN = os.getenv("KAGI_API_TOKEN")

# --- PROMPTS ---
# Prompts are loaded from .env first, then overridden by local files if they exist.

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT") or "You are a helpful assistant."
INJECTED_PROMPT = os.getenv("INJECTED_PROMPT") or ""

# Override from files if they exist
system_prompt_path = get_path("system_prompt.txt")
if os.path.exists(system_prompt_path):
    try:
        with open(system_prompt_path, "r", encoding="utf-8") as f:
            SYSTEM_PROMPT = f.read().strip()
    except Exception as e:
        print(f"⚠️ Warning: Failed to read system_prompt.txt: {e}")

injected_prompt_path = get_path("injected_prompt.txt")
if os.path.exists(injected_prompt_path):
    try:
        with open(injected_prompt_path, "r", encoding="utf-8") as f:
            INJECTED_PROMPT = f.read().strip()
    except Exception as e:
        print(f"⚠️ Warning: Failed to read injected_prompt.txt: {e}")

# --- VARIABLES FROM CONFIG.TXT (LEGACY SUPPORT) ---
# We initialize defaults here. If config.txt exists, we exec it to override.
# NOTE: Ideally, move these to .env

ADMIN_ROLE_IDS = []
ADMIN_USER_IDS = []
ADMIN_FLAVOR_TEXT = " (Seraph)"
SPECIAL_ROLE_IDS = []
SPECIAL_FLAVOR_TEXT = " (Chiara)"

MY_SYSTEM_ID = "your_pluralkit_system_id"
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
BUG_REPORT_CHANNEL_ID = 0
STARTUP_CHANNEL_ID = 0
BOT_ROLE_IDS = []
MODEL_TEMPERATURE = 0.6
CONTEXT_WINDOW = 20

# Default Status Messages
MSG_REBOOT_HEADER = "# <a:Thinking:1322962569300017214> Rebooting . . ."
MSG_REBOOT_SUB = "-# Waking {current}/{total} Uplinks" 
MSG_STARTUP_HEADER = "# <a:SATVRNCommand:1301834555086602240> System Online"
MSG_STARTUP_SUB = "-# NyxOS v2.0"
MSG_CRASH_HEADER = "# <a:SeraphBurningFuck:1304766240648204298> I just crashed! <a:SeraphCryHandsSnap:1297004800117837906>"
MSG_CRASH_SUB = "-# unexpected shutdown detected"
MSG_ACTIVE_UPLINKS_HEADER = "# Active Uplinks"

# Dropbox Configuration Defaults
DROPBOX_APP_KEY = None
DROPBOX_APP_SECRET = None
DROPBOX_REFRESH_TOKEN = None

# Backup Targets Defaults
BACKUP_TARGETS = {}

# Backup Pings Defaults
ADMIN_PINGS = {}

# Backup Flavor Text Defaults
BACKUP_FLAVOR_TEXT = {
    "START": "🚀 Starting backup process...",
    "DOWNLOAD": "📥 Downloading...",
    "ARCHIVE": "📦 Archiving files...",
    "UPLOAD": "☁️ Uploading to Dropbox...",
    "FINISH": "✨ Generating final report...",
    "TIME_LABEL": "⏳ **Time Elapsed:**",
    "PROCESSING_LABEL": "📂 **Processing:**"
}

# Backup Messaging Defaults
BACKUP_COMPLETION_TEMPLATE = "**Backup Complete:** {size} | [Download]({link})"
TEMPLE_BACKUP_PROMPT = "Say something nice about the backup."
WM_BACKUP_PROMPT = "Be snarky about the backup."

try:
    with open(get_path("config.txt"), "r") as f:
        # Be careful with exec. It executes in the current scope.
        exec(f.read(), globals())
except FileNotFoundError:
    pass
except Exception as e:
    print(f"⚠️ Warning: Error loading config.txt: {e}")

# --- DATA SANITIZATION ---
# Ensure IDs are integers to prevent auth failures
try:
    ADMIN_ROLE_IDS = [int(uid) for uid in ADMIN_ROLE_IDS]
    ADMIN_USER_IDS = [int(uid) for uid in ADMIN_USER_IDS]
    SPECIAL_ROLE_IDS = [int(uid) for uid in SPECIAL_ROLE_IDS]
    BOT_ROLE_IDS = [int(uid) for uid in BOT_ROLE_IDS]
except Exception as e:
    print(f"⚠️ Warning: Failed to sanitize Role IDs: {e}")

# Overrides from ENV (take precedence over config.txt)
if os.getenv("MY_SYSTEM_ID"): MY_SYSTEM_ID = os.getenv("MY_SYSTEM_ID")
if os.getenv("LM_STUDIO_URL"): LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
if os.getenv("BUG_REPORT_CHANNEL_ID"): BUG_REPORT_CHANNEL_ID = int(os.getenv("BUG_REPORT_CHANNEL_ID"))
if os.getenv("STARTUP_CHANNEL_ID"): STARTUP_CHANNEL_ID = int(os.getenv("STARTUP_CHANNEL_ID"))
if os.getenv("MODEL_TEMPERATURE"): MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE"))
if os.getenv("CONTEXT_WINDOW"): CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW"))

# New Configs
BAR_DEBOUNCE_SECONDS = 3.0
NOTIFICATION_EMOJI = "<a:SeraphExclamark:1317628268299554877>"

if os.getenv("BAR_DEBOUNCE_SECONDS"): BAR_DEBOUNCE_SECONDS = float(os.getenv("BAR_DEBOUNCE_SECONDS"))
if os.getenv("NOTIFICATION_EMOJI"): NOTIFICATION_EMOJI = os.getenv("NOTIFICATION_EMOJI")

# Backup IDs
TEMPLE_GUILD_ID = 0
WM_GUILD_ID = 0

if os.getenv("TEMPLE_GUILD_ID"): TEMPLE_GUILD_ID = int(os.getenv("TEMPLE_GUILD_ID"))
if os.getenv("WM_GUILD_ID"): WM_GUILD_ID = int(os.getenv("WM_GUILD_ID"))

# --- PLURALKIT API CONFIGURATION ---
# Check for overrides from Environment
if os.getenv("USE_LOCAL_PLURALKIT"):
    USE_LOCAL_PLURALKIT = os.getenv("USE_LOCAL_PLURALKIT").lower() in ("true", "1", "t")
if os.getenv("LOCAL_PLURALKIT_API_URL"):
    LOCAL_PLURALKIT_API_URL = os.getenv("LOCAL_PLURALKIT_API_URL")

# Construct Endpoints
pk_base_url = LOCAL_PLURALKIT_API_URL if USE_LOCAL_PLURALKIT else "https://api.pluralkit.me/v2"

PLURALKIT_MESSAGE_API = f"{pk_base_url}/messages/{{}}"
PLURALKIT_USER_API = f"{pk_base_url}/users/{{}}"
PLURALKIT_SYSTEM_MEMBERS = f"{pk_base_url}/systems/{{}}/members"
PLURALKIT_SYSTEM_API = f"{pk_base_url}/systems/{{}}"

# Construct Template (Last step to ensure all overrides are applied)
if INJECTED_PROMPT:
    SYSTEM_PROMPT_TEMPLATE = f"{SYSTEM_PROMPT}\n\n{INJECTED_PROMPT}"
else:
    SYSTEM_PROMPT_TEMPLATE = SYSTEM_PROMPT

# --- USER TITLES / FLAVOR TEXT ---
# This is the new system to replace hardcoded "Seraph" checks.
# Maps User ID (int) -> Title String
USER_TITLES = {}

# Load Custom Titles from JSON in .env or file could be added here
# For now, we allow direct manipulation or extensions in code.

DEFAULT_TITLE = " (Mortal)"

# --- ALLOWED CHANNELS ---
# Now managed via Database


# Ensure directories exist
os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

if not BOT_TOKEN:
    print("❌ CONFIG ERROR: BOT_TOKEN is missing. Check .env or token.txt")
    # We don't exit here to allow importing config for inspection, but main will fail.
