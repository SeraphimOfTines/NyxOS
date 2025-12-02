
import unittest
import discord
import sys
import os
import asyncio
from unittest.mock import MagicMock, patch

# Adjust path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import ui

class TestStatusBarView(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock config values if needed, though they are imported
        pass

    async def test_view_initialization_and_layout(self):
        """Test that StatusBarView initializes with the correct button layout."""
        
        # Create view
        view = ui.StatusBarView(content="Test", original_user_id=123, channel_id=456)
        
        # Check number of items
        # Expected: Drop All, Drop Check, Auto, Console Link, Delete = 5 buttons
        self.assertEqual(len(view.children), 5, "Should have 5 buttons")
        
        children = view.children
        
        # 1. Drop All
        btn1 = children[0]
        self.assertIsInstance(btn1, discord.ui.Button)
        self.assertEqual(btn1.custom_id, "bar_drop_all_btn")
        self.assertEqual(btn1.label, ui.FLAVOR_TEXT["BAR_DROP_ALL"])
        
        # 2. Drop Check
        btn2 = children[1]
        self.assertIsInstance(btn2, discord.ui.Button)
        self.assertEqual(btn2.custom_id, "bar_drop_check_btn")
        self.assertEqual(btn2.label, ui.FLAVOR_TEXT["BAR_DROP_CHECK"])
        
        # 3. Auto Mode
        btn3 = children[2]
        self.assertIsInstance(btn3, discord.ui.Button)
        self.assertEqual(btn3.custom_id, "bar_persist_btn")
        self.assertEqual(btn3.label, "Auto")
        
        # 4. Console Link
        btn4 = children[3]
        self.assertIsInstance(btn4, discord.ui.Button)
        # Check name of PartialEmoji
        self.assertEqual(btn4.emoji.name, "🖥️")
        self.assertIsNone(btn4.custom_id) # Link buttons have no custom_id
        expected_url = f"https://discord.com/channels/{config.TEMPLE_GUILD_ID}/{config.STARTUP_CHANNEL_ID}"
        self.assertEqual(btn4.url, expected_url)
        
        # 5. Delete
        btn5 = children[4]
        self.assertIsInstance(btn5, discord.ui.Button)
        self.assertEqual(btn5.custom_id, "bar_delete_btn")
        self.assertEqual(btn5.label, ui.FLAVOR_TEXT["BAR_DELETE"])

    async def test_callbacks_bound(self):
        """Test that callbacks are correctly bound to buttons."""
        view = ui.StatusBarView(content="Test", original_user_id=123, channel_id=456)
        
        # Check callbacks (except link button)
        self.assertEqual(view.children[0].callback, view.drop_all_callback)
        self.assertEqual(view.children[1].callback, view.drop_check_callback)
        self.assertEqual(view.children[2].callback, view.persist_callback)
        self.assertEqual(view.children[4].callback, view.delete_callback)

if __name__ == '__main__':
    unittest.main()
