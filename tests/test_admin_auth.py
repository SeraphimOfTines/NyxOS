import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers
import config

class TestAdminAuth(unittest.TestCase):
    
    @patch.object(config, 'ADMIN_ROLE_IDS', [999])
    @patch.object(config, 'SPECIAL_ROLE_IDS', [])
    def test_is_authorized_member_with_role(self):
        """Test 1: Regular Member with correct Role ID."""
        member = MagicMock()
        role = MagicMock()
        role.id = 999
        member.roles = [role]
        
        self.assertTrue(helpers.is_authorized(member))

    @patch.object(config, 'ADMIN_ROLE_IDS', [999])
    @patch.object(config, 'SPECIAL_ROLE_IDS', [])
    def test_is_authorized_member_without_role(self):
        """Test 2: Regular Member without Role."""
        member = MagicMock()
        role = MagicMock()
        role.id = 100
        member.roles = [role]
        
        self.assertFalse(helpers.is_authorized(member))

    @patch.object(config, 'ADMIN_ROLE_IDS', [999])
    @patch.object(config, 'SPECIAL_ROLE_IDS', [])
    def test_pk_proxy_lookup_logic(self):
        """
        Test 3: Simulate PK Proxy lookup failure due to String vs Int ID mismatch.
        This mirrors the logic in NyxOS.py
        """
        
        # Mock Data
        pk_sender_id_str = "12345" # PK returns string
        pk_sender_id_int = 12345
        
        guild = MagicMock()
        
        # Mock get_member behavior: Returns Member if INT, None if STRING (Simulating discord.py)
        def get_member_side_effect(user_id):
            if isinstance(user_id, int) and user_id == pk_sender_id_int:
                m = MagicMock()
                r = MagicMock()
                r.id = 999 # Admin Role
                m.roles = [r]
                return m
            return None
        
        guild.get_member.side_effect = get_member_side_effect
        
        # --- Scenario A: Current Buggy Logic (Passing String) ---
        member_obj = guild.get_member(pk_sender_id_str) 
        # member_obj should be None because we passed a string
        self.assertIsNone(member_obj)
        
        # Fallback auth check (checks ID against Role List)
        is_auth = helpers.is_authorized(pk_sender_id_str)
        self.assertFalse(is_auth)
        
        # --- Scenario B: Fixed Logic (Casting to Int) ---
        member_obj_fixed = guild.get_member(int(pk_sender_id_str))
        self.assertIsNotNone(member_obj_fixed)
        self.assertTrue(helpers.is_authorized(member_obj_fixed))

if __name__ == '__main__':
    unittest.main()