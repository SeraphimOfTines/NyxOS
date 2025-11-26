import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import json
import asyncio
from datetime import datetime

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers
import memory_manager
import config
import services
import command_handler
import message_processor

class TestHelpers(unittest.TestCase):
    """Tests for helpers.py"""

    def test_is_authorized(self):
        print("\n[TestHelpers] Testing is_authorized logic...")
        # Test Seraph ID
        config.SERAPH_IDS = [12345]
        config.CHIARA_IDS = []
        print(f"  > Checking Seraph ID {config.SERAPH_IDS[0]}...")
        self.assertTrue(helpers.is_authorized(12345))
        print("    [OK] Access Granted.")
        
        # Test Chiara ID
        config.SERAPH_IDS = []
        config.CHIARA_IDS = [67890]
        print(f"  > Checking Chiara ID {config.CHIARA_IDS[0]}...")
        self.assertTrue(helpers.is_authorized(67890))
        print("    [OK] Access Granted.")
        
        # Test Unauthorized
        print("  > Checking Unauthorized ID 99999...")
        self.assertFalse(helpers.is_authorized(99999))
        print("    [OK] Access Denied.")

    def test_clean_name_logic(self):
        print("\n[TestHelpers] Testing clean_name_logic...")
        # Test with tag
        print("  > Cleaning name 'User [TAG]' with tag 'TAG'...")
        self.assertEqual(helpers.clean_name_logic("User [TAG]", "TAG"), "User")
        print("    [OK] Cleaned.")
        
        # Test without tag
        print("  > Cleaning name 'User' with tag 'TAG'...")
        self.assertEqual(helpers.clean_name_logic("User", "TAG"), "User")
        print("    [OK] Unchanged.")
        
        # Test with None
        print("  > Cleaning name 'User' with None tag...")
        self.assertEqual(helpers.clean_name_logic("User", None), "User")
        print("    [OK] Unchanged.")

    def test_matches_proxy_tag(self):
        print("\n[TestHelpers] Testing matches_proxy_tag...")
        tags = [{'prefix': 'S:', 'suffix': ''}, {'prefix': '', 'suffix': '-C'}]
        # Match Prefix
        print("  > Testing prefix 'S:Hello'...")
        self.assertTrue(helpers.matches_proxy_tag("S:Hello", tags))
        print("    [OK] Matched.")
        
        # Match Suffix
        print("  > Testing suffix 'Hello-C'...")
        self.assertTrue(helpers.matches_proxy_tag("Hello-C", tags))
        print("    [OK] Matched.")
        
        # No Match
        print("  > Testing no-match 'Hello'...")
        self.assertFalse(helpers.matches_proxy_tag("Hello", tags))
        print("    [OK] Not Matched.")

class TestMemoryManager(unittest.TestCase):
    """Tests for memory_manager.py"""

    def setUp(self):
        # Mock file operations for setup
        self.test_dir = "tests/temp_memory"
        os.makedirs(self.test_dir, exist_ok=True)
        config.GOOD_BOT_FILE = os.path.join(self.test_dir, "goodbot.json")
        config.MEMORY_DIR = self.test_dir
        config.LOGS_DIR = os.path.join(self.test_dir, "Logs")
        print(f"\n[TestMemoryManager] Setup temp dir: {self.test_dir}")

    def tearDown(self):
        # Cleanup
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        print(f"  > Teardown temp dir: {self.test_dir}")

    def test_increment_good_bot(self):
        print("  > Testing increment_good_bot...")
        count = memory_manager.increment_good_bot(123, "TestUser")
        print(f"    First increment: {count} (Expected: 1)")
        self.assertEqual(count, 1)
        
        count = memory_manager.increment_good_bot(123, "TestUser")
        print(f"    Second increment: {count} (Expected: 2)")
        self.assertEqual(count, 2)
        
        # Verify file content
        print("  > Verifying JSON persistence...")
        with open(config.GOOD_BOT_FILE, 'r') as f:
            data = json.load(f)
            self.assertEqual(data['123']['count'], 2)
        print("    [OK] File saved correctly.")

class TestServices(unittest.IsolatedAsyncioTestCase):
    """Tests for services.py (Async)"""

    async def test_generate_search_queries_sanitization(self):
        print("\n[TestServices] Testing generate_search_queries sanitization...")
        # Mock the HTTP session and response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '1. query one\n* query two\n&web query three'}}]
        }
        
        # Context manager mock for session.post
        mock_post = AsyncMock()
        mock_post.__aenter__.return_value = mock_response
        
        services.service.http_session = MagicMock()
        services.service.http_session.post.return_value = mock_post
        
        # Run
        print("  > Invoking generate_search_queries...")
        queries = await services.service.generate_search_queries("test", [])
        print(f"    Output: {queries}")
        
        # Assertions
        self.assertIn("query one", queries)
        self.assertIn("query two", queries) 
        self.assertIn("query three", queries) # Should strip &web
        self.assertNotIn("1. query one", queries) # Should strip numbering
        print("    [OK] Sanitization successful.")

class TestCommandHandler(unittest.IsolatedAsyncioTestCase):
    """Tests for command_handler.py"""

    async def test_handle_prefix_command_reboot_auth(self):
        print("\n[TestCommandHandler] Testing &reboot authorization...")
        client = MagicMock()
        message = AsyncMock()
        message.content = "&reboot"
        message.author.id = 999 # Unauthorized
        
        # Mock UI constants
        with patch('ui.FLAVOR_TEXT', {"NOT_AUTHORIZED": "No.", "REBOOT_MESSAGE": "Rebooting"}):
            print("  > Sending &reboot as Unauthorized User 999...")
            await command_handler.handle_prefix_command(client, message)
            
        # Should send unauthorized message
        message.channel.send.assert_called_with("No.")
        print("    [OK] Bot replied 'No.'")
        # Should NOT close client
        client.close.assert_not_called()
        print("    [OK] Client.close() was NOT called.")

def run_suite():
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryManager))
    suite.addTests(loader.loadTestsFromTestCase(TestServices))
    suite.addTests(loader.loadTestsFromTestCase(TestCommandHandler))
    
    # Run
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result

if __name__ == '__main__':
    run_suite()
