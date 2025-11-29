import sys
import os
from unittest.mock import MagicMock

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import helpers

def diagnose():
    print("--- DIAGNOSTIC START ---")
    print(f"Loaded ADMIN_ROLE_IDS: {config.ADMIN_ROLE_IDS}")
    print(f"Loaded SPECIAL_ROLE_IDS: {config.SPECIAL_ROLE_IDS}")

    # IDs from the user's config.txt
    target_role_id = 1224304985756536922 # From config.txt
    
    print(f"\nTesting Auth for Mock Member with Role ID: {target_role_id}")
    
    mock_member = MagicMock()
    mock_role = MagicMock()
    mock_role.id = target_role_id
    mock_member.roles = [mock_role]
    mock_member.__str__.return_value = "MockUser"
    
    result = helpers.is_authorized(mock_member)
    print(f"is_authorized Result: {result}")
    
    if not result:
        print("FAILURE: User has the role, but is_authorized returned False.")
    else:
        print("SUCCESS: User recognized as Admin.")
        
    print("--- DIAGNOSTIC END ---")

if __name__ == "__main__":
    diagnose()
