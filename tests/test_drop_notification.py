import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Adjust path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory_manager
import NyxOS

class TestDropStatusBarNotification(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.client = NyxOS.LMStudioBot()
        self.client.active_bars = {}
        self.client.get_channel = MagicMock()
        self.client.fetch_channel = AsyncMock()
        self.client.handle_bar_touch = AsyncMock()
        self.client.cleanup_recent_artifacts = AsyncMock()
        self.client.update_console_status = AsyncMock()  # Mock console update
        self.client.loop = asyncio.get_running_loop() # Mock loop for create_task

    @patch("NyxOS.memory_manager")
    async def test_drop_status_bar_clears_notification(self, mock_mm):
        # Setup: Channel with notification active
        channel_id = 12345
        self.client.active_bars[channel_id] = {
            "message_id": 100,
            "content": "Bar Content",
            "user_id": 999,
            "persisting": False,
            "checkmark_message_id": 100,
            "has_notification": True, # Initial state: Has Notification
            "current_prefix": "Prefix"
        }
        
        mock_channel = AsyncMock()
        mock_channel.id = channel_id
        mock_channel.guild.id = 555
        self.client.get_channel.return_value = mock_channel
        
        # Correctly mock Async Iterator for history
        class AsyncIter:
            def __init__(self, items):
                self.items = list(items)
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)

        mock_msg = AsyncMock()
        mock_msg.id = 100
        mock_msg.content = "Bar Content"
        mock_channel.history.return_value = AsyncIter([mock_msg])

        mock_channel.fetch_message.return_value = AsyncMock(id=100, content="Bar Content")
        
        # Run Drop
        await self.client.drop_status_bar(channel_id, move_bar=True, move_check=True, manual=True)
        
        # Assert notification flag is cleared in memory
        self.assertFalse(self.client.active_bars[channel_id]["has_notification"])
        
        # Assert DB update called
        mock_mm.set_bar_notification.assert_called_with(channel_id, False)
        
        # Assert Console Update Called
        # Note: Since we used asyncio.create_task, we might need to yield to loop to let it run
        await asyncio.sleep(0) 
        self.client.update_console_status.assert_called()

if __name__ == '__main__':
    unittest.main()