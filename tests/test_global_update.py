import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import memory_manager

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestGlobalUpdate(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Create instance
        self.client = NyxOS.LMStudioBot()
        
        # Mock Loop
        self.client.loop = MagicMock()
        
        # Mock Active Bars
        self.client.active_bars = {
            100: {
                "message_id": 101, 
                "content": "<a:Watching:123> Old Text", 
                "user_id": 1, 
                "persisting": False,
                "checkmark_message_id": None
            },
            200: {
                "message_id": 201, 
                "content": "<a:NotWatching:456> Old Text", 
                "user_id": 2, 
                "persisting": True, 
                "checkmark_message_id": 201 # Merged checkmark
            }
        }
        self.client.active_views = {}

        # Mock Startup Bar Message (Console Channel)
        self.client.startup_bar_msg = AsyncMock()

        # Mock DB functions
        self.mock_set_master = patch('memory_manager.set_master_bar').start()
        self.mock_save_bar = patch('memory_manager.save_bar').start()

    def tearDown(self):
        patch.stopall()

    async def test_global_update_flow(self):
        """
        Tests that global_update_bars:
        1. Updates Master Bar in DB.
        2. Updates Console Channel Bar.
        3. Propagates to active bars (preserving prefixes).
        """
        # Setup Channel/Message Mocks
        mock_channel_100 = MagicMock()
        mock_msg_101 = AsyncMock()
        mock_channel_100.fetch_message = AsyncMock(return_value=mock_msg_101)
        
        mock_channel_200 = MagicMock()
        mock_msg_201 = AsyncMock()
        mock_channel_200.fetch_message = AsyncMock(return_value=mock_msg_201)
        
        # Setup get_channel/fetch_channel side effects
        async def get_ch(cid):
            if cid == 100: return mock_channel_100
            if cid == 200: return mock_channel_200
            return None
            
        self.client.get_channel = MagicMock(side_effect=lambda cid: mock_channel_100 if cid == 100 else mock_channel_200)
        self.client.fetch_channel = AsyncMock(side_effect=get_ch)
        
        # Execute Global Update
        new_text = "Global System Update"
        count = await self.client.global_update_bars(new_text)
        
        # Assertions
        
        # 1. Verify Master Bar DB Update
        self.mock_set_master.assert_called_once_with("Global System Update")
        
        # 2. Verify Console Bar Update
        self.client.startup_bar_msg.edit.assert_called_once_with(content="Global System Update")
        
        # 3. Verify Active Bars Updated
        self.assertEqual(count, 2, f"Should update both active bars, but got {count}")
        
        # Check Message 101 (Simple)
        # Should preserve <a:Watching:123>
        mock_msg_101.edit.assert_called_once()
        args, kwargs = mock_msg_101.edit.call_args
        content_101 = kwargs.get('content')
        self.assertIn("<a:Watching:123>", content_101)
        self.assertIn("Global System Update", content_101)
        
        # Check Message 201 (Merged Checkmark)
        # Should preserve <a:NotWatching:456> AND append Checkmark
        mock_msg_201.edit.assert_called_once()
        args, kwargs = mock_msg_201.edit.call_args
        content_201 = kwargs.get('content')
        self.assertIn("<a:NotWatching:456>", content_201)
        self.assertIn("Global System Update", content_201)
        self.assertIn(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], content_201)
        
        # 4. Verify DB Save for Active Bars
        self.assertEqual(self.mock_save_bar.call_count, 2)

    async def test_global_update_console_bar_missing(self):
        """Test that it proceeds if console bar is missing."""
        self.client.startup_bar_msg = None # Simulate missing bar
        self.client.active_bars = {} # No active bars for this test to avoid setup noise
        
        # Execute
        await self.client.global_update_bars("New Text")
        
        # Should verify master bar still set
        self.mock_set_master.assert_called_once_with("New Text")
        
        # Should not crash

if __name__ == '__main__':
    unittest.main()
