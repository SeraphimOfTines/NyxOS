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
        # Mock config values if needed
        pass

    async def test_view_initialization_and_layout(self):
        """Test that StatusBarView initializes with the correct button layout."""
        
        # Create view (persisting=False -> Manual)
        view = ui.StatusBarView(content="Test", original_user_id=123, channel_id=456, persisting=False)
        
        # Check number of items
        # Expected: Drop All, Auto, Symbols, Console Link, Delete = 5 buttons
        self.assertEqual(len(view.children), 5, "Should have 5 buttons")
        
        children = view.children
        
        # 1. Drop All
        btn1 = children[0]
        self.assertIsInstance(btn1, discord.ui.Button)
        self.assertEqual(btn1.custom_id, "bar_drop_all_btn")
        self.assertEqual(btn1.label, ui.FLAVOR_TEXT["BAR_DROP_ALL"])
        
        # 2. Auto Mode (Manual initially)
        btn2 = children[1]
        self.assertIsInstance(btn2, discord.ui.Button)
        self.assertEqual(btn2.custom_id, "bar_persist_btn")
        self.assertEqual(btn2.emoji.name, "Ⓜ️")
        self.assertIsNone(btn2.label)
        self.assertEqual(btn2.style, discord.ButtonStyle.secondary)
        
        # 3. Symbols Link
        btn3 = children[2]
        self.assertIsInstance(btn3, discord.ui.Button)
        self.assertEqual(btn3.label, "Symbols")
        
        # 4. Console Link
        btn4 = children[3]
        self.assertIsInstance(btn4, discord.ui.Button)
        self.assertEqual(btn4.emoji.name, "🖥️")
        
        # 5. Delete
        btn5 = children[4]
        self.assertIsInstance(btn5, discord.ui.Button)
        self.assertEqual(btn5.custom_id, "bar_delete_btn")
        self.assertEqual(btn5.label, ui.FLAVOR_TEXT["BAR_DELETE"])

    async def test_view_initialization_auto(self):
        """Test that StatusBarView initializes with Auto state correctly."""
        view = ui.StatusBarView(content="Test", original_user_id=123, channel_id=456, persisting=True)
        
        btn_auto = view.children[1]
        self.assertEqual(btn_auto.emoji.name, "🅰️")
        self.assertIsNone(btn_auto.label)
        self.assertEqual(btn_auto.style, discord.ButtonStyle.success)

    async def test_callbacks_bound(self):
        """Test that callbacks are correctly bound to buttons."""
        view = ui.StatusBarView(content="Test", original_user_id=123, channel_id=456)
        
        # Check callbacks
        self.assertEqual(view.children[0].callback, view.drop_all_callback)
        self.assertEqual(view.children[1].callback, view.persist_callback)
        # 2 & 3 are links
        self.assertEqual(view.children[4].callback, view.delete_callback)

    async def test_console_layout(self):
        """Test ConsoleControlView has 5 buttons in correct order."""
        view = ui.ConsoleControlView()
        
        # Check children count
        self.assertEqual(len(view.children), 5)
        
        # 1. Idle (Emoji='💤', Label=None)
        self.assertEqual(view.children[0].emoji.name, "💤")
        
        # 2. Sleep
        self.assertEqual(view.children[1].emoji.name, "🛏️")
        
        # 3. Symbols (Label='Symbols')
        self.assertEqual(view.children[2].label, "Symbols")
        
        # 4. Reboot
        self.assertEqual(view.children[3].emoji.name, "🔄")
        
        # 5. Shutdown
        self.assertEqual(view.children[4].emoji.name, "🛑")

if __name__ == '__main__':
    unittest.main()