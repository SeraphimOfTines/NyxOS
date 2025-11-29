import memory_manager
import logging

# Configure basic logging to stdout
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Diagnostic")

try:
    print("--- DIAGNOSTIC START ---")
    
    # 1. Check Allowed Channels
    allowed = memory_manager.get_allowed_channels()
    print(f"Allowed Channels List ({type(allowed)}): {allowed}")
    
    if not allowed:
        print("⚠️ WARNING: No allowed channels found in database.")
    else:
        print(f"✅ Found {len(allowed)} allowed channels.")
        
    # 2. Check Server Settings Raw (if possible via public method, else infer)
    # memory_manager.get_server_setting calls db.get_setting
    
    print("--- DIAGNOSTIC END ---")

except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()
