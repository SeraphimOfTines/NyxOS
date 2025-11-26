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
ALLOWED_CHANNELS_FILE = get_path("allowed_channels.json")
RESTART_META_FILE = get_path("restart_metadata.json")
GOOD_BOT_FILE = get_path("goodbot.json")
BUFFER_FILE = get_path("buffer.txt")
HEARTBEAT_FILE = get_path("heartbeat.txt")
SHUTDOWN_FLAG_FILE = get_path("shutdown.flag")
COMMAND_STATE_FILE = get_path("command_state.hash")
SUPPRESSED_USERS_FILE = get_path("suppressed_users.json")
SERVER_SETTINGS_FILE = get_path("server_settings.json")

# API Endpoints
PLURALKIT_MESSAGE_API = "https://api.pluralkit.me/v2/messages/{}"
PLURALKIT_USER_API = "https://api.pluralkit.me/v2/users/{}"
PLURALKIT_SYSTEM_MEMBERS = "https://api.pluralkit.me/v2/systems/{}/members"
KAGI_SEARCH_URL = "https://kagi.com/api/v0/search"

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

SERAPH_IDS = [] 
CHIARA_IDS = [] 
MY_SYSTEM_ID = "your_pluralkit_system_id"
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
BUG_REPORT_CHANNEL_ID = 0
STARTUP_CHANNEL_ID = 0
BOT_ROLE_IDS = []
MODEL_TEMPERATURE = 0.6
CONTEXT_WINDOW = 20

try:
    with open(get_path("config.txt"), "r") as f:
        # Be careful with exec. It executes in the current scope.
        exec(f.read(), globals())
except FileNotFoundError:
    pass
except Exception as e:
    print(f"⚠️ Warning: Error loading config.txt: {e}")

# Overrides from ENV (take precedence over config.txt)
if os.getenv("MY_SYSTEM_ID"): MY_SYSTEM_ID = os.getenv("MY_SYSTEM_ID")
if os.getenv("LM_STUDIO_URL"): LM_STUDIO_URL = os.getenv("LM_STUDIO_URL")
if os.getenv("BUG_REPORT_CHANNEL_ID"): BUG_REPORT_CHANNEL_ID = int(os.getenv("BUG_REPORT_CHANNEL_ID"))
if os.getenv("STARTUP_CHANNEL_ID"): STARTUP_CHANNEL_ID = int(os.getenv("STARTUP_CHANNEL_ID"))
if os.getenv("MODEL_TEMPERATURE"): MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE"))
if os.getenv("CONTEXT_WINDOW"): CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW"))

# Construct Template (Last step to ensure all overrides are applied)
if INJECTED_PROMPT:
    SYSTEM_PROMPT_TEMPLATE = f"{SYSTEM_PROMPT}\n\n{INJECTED_PROMPT}"
else:
    SYSTEM_PROMPT_TEMPLATE = SYSTEM_PROMPT

# --- USER TITLES / FLAVOR TEXT ---
# This is the new system to replace hardcoded "Seraph" checks.
# Maps User ID (int) -> Title String
USER_TITLES = {}

# Populate from Legacy
for uid in SERAPH_IDS:
    USER_TITLES[uid] = " (Seraph)" # Default for migration
for uid in CHIARA_IDS:
    USER_TITLES[uid] = " (Chiara)" # Default for migration

# Load Custom Titles from JSON in .env or file could be added here
# For now, we allow direct manipulation or extensions in code.

DEFAULT_TITLE = " (Mortal)"

# --- ALLOWED CHANNELS ---
ALLOWED_CHANNEL_IDS = []
if os.path.exists(ALLOWED_CHANNELS_FILE):
    try:
        with open(ALLOWED_CHANNELS_FILE, "r") as f:
            ALLOWED_CHANNEL_IDS = json.load(f)
    except:
        ALLOWED_CHANNEL_IDS = []

def save_allowed_channels(channels_list):
    try:
        with open(ALLOWED_CHANNELS_FILE, "w") as f:
            json.dump(channels_list, f, indent=4)
        global ALLOWED_CHANNEL_IDS
        ALLOWED_CHANNEL_IDS = channels_list
    except Exception as e:
        print(f"⚠️ Failed to save allowed channels: {e}")

# Ensure directories exist
os.makedirs(MEMORY_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

if not BOT_TOKEN:
    print("❌ CONFIG ERROR: BOT_TOKEN is missing. Check .env or token.txt")
    # We don't exit here to allow importing config for inspection, but main will fail.
