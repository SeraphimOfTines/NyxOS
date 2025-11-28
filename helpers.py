import mimetypes
import re
from datetime import datetime, timedelta, timezone
import logging
import config

logger = logging.getLogger("Helpers")

def get_safe_mime_type(attachment):
    filename = attachment.filename.lower()
    
    # 1. Priority: Check Extension
    if filename.endswith('.png'): return 'image/png'
    if filename.endswith(('.jpg', '.jpeg')): return 'image/jpeg'
    if filename.endswith('.webp'): return 'image/webp'
    
    # 2. Trust Discord
    if attachment.content_type and attachment.content_type.startswith('image/'):
        return attachment.content_type

    # 3. System Registry Fallback
    guessed_type, _ = mimetypes.guess_type(attachment.filename)
    if guessed_type and guessed_type.startswith('image/'):
        return guessed_type

    # 4. Ultimate Fallback
    return 'image/png'

def get_system_time():
    utc_now = datetime.now(timezone.utc)
    pst_offset = timedelta(hours=-8) # PST
    pst_now = utc_now.astimezone(timezone(pst_offset))
    return pst_now.strftime("%A, %B %d, %Y"), pst_now.strftime("%I:%M %p")

def matches_proxy_tag(content, tags):
    for tag in tags:
        prefix = tag.get('prefix') or ""
        suffix = tag.get('suffix') or ""
        if not prefix and not suffix: continue
        
        c_clean = content.strip()
        p_clean = prefix.strip()
        s_clean = suffix.strip()
        
        match = True
        if p_clean and not c_clean.startswith(p_clean): match = False
        if s_clean and not c_clean.endswith(s_clean): match = False
        if match: return True
    return False

def clean_name_logic(raw_name, system_tag=None):
    name = raw_name
    if system_tag:
        if system_tag in name: name = name.replace(system_tag, "")
        else:
            stripped_tag = system_tag.strip()
            if stripped_tag in name: name = name.replace(stripped_tag, "")
    return re.sub(r'\s*([\[\(\{<\|⛩].*?[\]\}\)>\|⛩])\s*', '', name).strip()

def get_identity_suffix(user_obj, system_id, member_name=None, my_system_members=None):
    """
    Determines the suffix/title for a user based on Role, ID or System status.
    Uses USER_TITLES from config for customization.
    """
    user_id = user_obj.id if hasattr(user_obj, 'id') else user_obj

    # 1. Check exact User ID match in Config
    if user_id in config.USER_TITLES:
        return config.USER_TITLES[user_id]

    # 2. Check Role-based Titles
    if hasattr(user_obj, "roles"):
        role_ids = [r.id for r in user_obj.roles]
        if any(rid in config.ADMIN_ROLE_IDS for rid in role_ids):
            return config.ADMIN_FLAVOR_TEXT
        if any(rid in config.SPECIAL_ROLE_IDS for rid in role_ids):
            return config.SPECIAL_FLAVOR_TEXT
        
    # 3. Check if they are part of the 'Own System' (Legacy Seraph Logic)
    is_system_member = False
    if system_id == config.MY_SYSTEM_ID:
        is_system_member = True
    elif my_system_members and member_name in my_system_members:
        is_system_member = True
        
    if is_system_member:
        return config.ADMIN_FLAVOR_TEXT # Default system members to Admin Title? Or keep separate? Assuming Admin Title for now.

    # 4. Default
    return config.DEFAULT_TITLE

def is_authorized(user_obj):
    """Checks if a user is authorized (Admin/Special)."""
    # Handle raw IDs gracefully
    if isinstance(user_obj, (int, str)):
        try:
            uid = int(user_obj)
            # Note: This checks if the User ID is in the Role ID list. 
            # This is valid if the user put their User ID in the config, 
            # but usually these lists contain Role IDs.
            if uid in config.ADMIN_ROLE_IDS: return True
            if uid in config.SPECIAL_ROLE_IDS: return True
        except: pass
        logger.debug(f"Auth Failed for ID {user_obj}: Not in Admin/Special lists.")
        return False

    # Check object ID (Permissive)
    if hasattr(user_obj, "id"):
        if user_obj.id in config.ADMIN_ROLE_IDS: return True
        if user_obj.id in config.SPECIAL_ROLE_IDS: return True

    # Check Roles
    if hasattr(user_obj, "roles"):
        role_ids = [r.id for r in user_obj.roles]
        if any(rid in config.ADMIN_ROLE_IDS for rid in role_ids): return True
        if any(rid in config.SPECIAL_ROLE_IDS for rid in role_ids): return True
        
        # Debug Log for failure
        # logger.debug(f"Auth Failed for {user_obj}: Roles {role_ids} not in Admin {config.ADMIN_ROLE_IDS}")
    
    return False

def sanitize_llm_response(text):
    """
    Cleans up the raw text response from the LLM.
    1. Removes leading markdown headers (#) to prevent 'shouting'.
    2. Removes mid-text headers.
    3. Removes Admin/Special flavor text tags.
    4. Removes (re: ...) prefixes.
    """
    if not text: return ""
    
    # Strip markdown headers (#) at start of lines
    text = re.sub(r'^#+\s*', '', text)
    text = text.replace('\n#', '\n') 
    
    # Remove Identity Tags
    text = text.replace(config.ADMIN_FLAVOR_TEXT, "").replace(config.SPECIAL_FLAVOR_TEXT, "").replace("(Not Seraphim)", "")
    # Legacy cleanup just in case
    text = text.replace("(Seraph)", "").replace("(Chiara)", "")
    
    # Remove reply context
    text = re.sub(r'\s*\(re:.*?\)', '', text).strip()
    
    return text

def restore_hyperlinks(text):
    """
    Converts (Text)(URL) patterns back into [Text](URL) markdown links.
    The memory manager sanitizes brackets to parentheses to prevent injection,
    so this restores them for Discord display.
    """
    if not text: return ""
    return re.sub(r'\((.+?)\)\((https?://[^\s)]+)\)', r'[\1](\2)', text)
    