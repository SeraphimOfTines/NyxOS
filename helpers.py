import mimetypes
import re
from datetime import datetime, timedelta, timezone
import config

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

def get_identity_suffix(user_id, system_id, member_name=None, my_system_members=None):
    """
    Determines the suffix/title for a user based on ID or System status.
    Uses USER_TITLES from config for customization.
    """
    # 1. Check exact User ID match in Config
    if user_id in config.USER_TITLES:
        return config.USER_TITLES[user_id]
        
    # 2. Check if they are part of the 'Own System' (Legacy Seraph Logic)
    is_system_member = False
    if system_id == config.MY_SYSTEM_ID:
        is_system_member = True
    elif my_system_members and member_name in my_system_members:
        is_system_member = True
        
    if is_system_member:
        return " (Seraph)"

    # 3. Default
    return config.DEFAULT_TITLE

def is_authorized(user_id):
    """Checks if a user is authorized (Admin/Mod)."""
    # Checks legacy lists or new logic if added.
    if user_id in config.SERAPH_IDS: return True
    if user_id in config.CHIARA_IDS: return True
    # Also check if they have an 'Admin' title in the new map? 
    # For safety, stick to ID lists for now.
    return False