import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import time
import asyncio

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock config
with patch.dict(os.environ, {"BOT_TOKEN": "test", "KAGI_API_TOKEN": "test"}):
    import NyxOS
    import ui

class TestBarOptimization(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.client = NyxOS.LMStudioBot()
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 999
        self.client.loop = asyncio.get_running_loop() # Mock loop
        self.client.active_bars = {}
        
    async def test_auto_drop_debounce(self):
        # Setup
        cid = 123
        # Mock drop_status_bar
        self.client.drop_status_bar = AsyncMock()
        
        # 1. Request Drop
        self.client.request_bar_drop(cid)
        
        # Verify deadline is set
        self.assertIn(cid, self.client.drop_deadlines)
        first_deadline = self.client.drop_deadlines[cid]
        self.assertAlmostEqual(first_deadline, time.time() + 3.0, delta=0.5)
        self.assertIn(cid, self.client.active_drop_tasks)
        
        # 2. Wait 1s and Request Again (Reset Timer)
        await asyncio.sleep(1.0)
        self.client.request_bar_drop(cid)
        
        second_deadline = self.client.drop_deadlines[cid]
        self.assertGreater(second_deadline, first_deadline)
        self.assertAlmostEqual(second_deadline, time.time() + 3.0, delta=0.5)
        
        # 3. Wait for completion (Total wait > 3s from start, > 3s from second request)
        # We need to wait long enough for the loop to finish.
        # We mocked sleep in the loop? No, real sleep. So this test will take ~3s.
        await asyncio.sleep(3.5) 
        
        # Verify drop called ONCE
        self.client.drop_status_bar.assert_called_once()
        self.assertNotIn(cid, self.client.active_drop_tasks)

    async def test_bar_optimization_at_bottom(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 100, # Old Bar
                "checkmark_message_id": 50, # Separate Check
                "persisting": False
            }
        }
        
        # Mock Channel and History
        channel = AsyncMock()
        channel.history = MagicMock()
        
        # Mock History: Last message IS the old bar
        last_msg = AsyncMock()
        last_msg.id = 100
        last_msg.content = "Bar"
        
        # Async iterator mock
        async def mock_history(limit=1):
            yield last_msg
            
        channel.history.side_effect = mock_history
        
        # Mock fetch_channel
        self.client.fetch_channel = AsyncMock(return_value=channel)
        self.client.get_channel = MagicMock(return_value=channel)
        
        # Mock internal methods
        self.client._register_bar_message = MagicMock()
        
        # Mock Channel fetch message (for checkmark deletion and bar edit)
        old_bar_msg = AsyncMock()
        old_bar_msg.id = 100
        old_bar_msg.content = "Bar"
        
        old_check_msg = AsyncMock()
        old_check_msg.id = 50
        
        async def mock_fetch(msg_id):
            if msg_id == 100: return old_bar_msg
            if msg_id == 50: return old_check_msg
            raise Exception("Not Found")
            
        channel.fetch_message.side_effect = mock_fetch
        
        with patch('memory_manager.save_channel_location'), \
             patch('memory_manager.save_bar'):
            
            # Execute Drop
            await self.client.drop_status_bar(cid, move_bar=True, move_check=True)
            
            # Verify:
            # 1. Old Bar NOT deleted (move_bar set to False internally)
            old_bar_msg.delete.assert_not_called()
            
            # 2. New Bar NOT sent
            channel.send.assert_not_called()
            
            # 3. Old Check deleted
            old_check_msg.delete.assert_called()
            
            # 4. Old Bar EDITED to include checkmark
            old_bar_msg.edit.assert_called()
            args, kwargs = old_bar_msg.edit.call_args
            content = kwargs.get('content')
            self.assertIn(ui.FLAVOR_TEXT['CHECKMARK_EMOJI'], content)