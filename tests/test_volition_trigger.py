import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import time
from volition import VolitionManager
from tests.mock_utils import AsyncIter
from datetime import datetime, timedelta

class TestVolitionTrigger(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_client = MagicMock()
        self.mock_client.user.id = 999
        self.mock_client.user.display_name = "Nyx"
        self.mock_client.channel_cutoff_times = {} # Default empty
        self.mock_client.emotional_core = MagicMock()
        self.mock_client.emotional_core.is_enabled.return_value = True
        self.mock_client.emotional_core.state = {
            "stats": {
                "energy": 100
            }
        }
        
        # Mock Services
        self.patcher = patch('services.service.get_chat_response', new_callable=AsyncMock)
        self.mock_get_response = self.patcher.start()
        self.mock_get_response.return_value = "Hello world"
        
        self.vm = VolitionManager(self.mock_client)
        self.vm.enabled = True
        
        # Mock Memory Manager
        self.mm_patcher = patch('memory_manager.get_volition_channels')
        self.mock_get_volition = self.mm_patcher.start()
        self.mock_get_volition.return_value = [123] # Allow channel 123

    async def asyncTearDown(self):
        self.patcher.stop()
        self.mm_patcher.stop()

    async def test_trigger_fetches_history_and_respects_cutoff(self):
        # 1. Setup Buffer (Trigger Condition)
        self.vm.buffer.append({
            "author": "User", 
            "content": "Hi", 
            "timestamp": time.time(), 
            "channel_id": 123
        })
        
        # 2. Setup Mock Channel & Messages
        mock_channel = MagicMock()
        mock_channel.id = 123
        self.mock_client.get_channel.return_value = mock_channel
        
        # Create timestamps
        now = datetime.now()
        t1 = now - timedelta(minutes=5) # Old
        t2 = now - timedelta(minutes=1) # New
        
        msg1 = MagicMock()
        msg1.clean_content = "Old Message"
        msg1.author.display_name = "User1"
        msg1.author.id = 101
        msg1.created_at = t1
        msg1.attachments = []
        
        msg2 = MagicMock()
        msg2.clean_content = "I am Nyx"
        msg2.author.display_name = "Nyx"
        msg2.author.id = 999 # Self
        msg2.created_at = t2
        msg2.attachments = []
        
        # Mock history returns NEWEST first usually in Discord API, 
        # but our code processes them and then reverses.
        # channel.history yields most recent first.
        mock_channel.history.return_value = AsyncIter([msg2, msg1]) 
        
        # 3. Set Cutoff to filter out msg1 (Old Message)
        cutoff_time = now - timedelta(minutes=2)
        self.mock_client.channel_cutoff_times = {123: cutoff_time}
        
        # 4. Run
        await self.vm.trigger_thought_process()
        
        # 5. Verify Call to LLM
        self.mock_get_response.assert_called_once()
        call_args = self.mock_get_response.call_args[0][0] # First arg is messages list
        
        # Check System Prompt
        sys_msg = call_args[0]['content']
        user_msg = call_args[1]['content']
        
        # Verify Context
        # Should contain "You (Nyx): I am Nyx"
        self.assertIn("You (Nyx): I am Nyx", user_msg)
        
        # Should NOT contain "User1: Old Message" (Filtered by cutoff)
        self.assertNotIn("Old Message", user_msg)

    async def test_trigger_includes_self_messages(self):
        # 1. Setup Buffer
        self.vm.buffer.append({
            "author": "User", 
            "content": "Hi", 
            "timestamp": time.time(), 
            "channel_id": 123
        })
        
        mock_channel = MagicMock()
        mock_channel.id = 123
        self.mock_client.get_channel.return_value = mock_channel
        
        msg_self = MagicMock()
        msg_self.clean_content = "My own words"
        msg_self.author.id = 999
        msg_self.created_at = datetime.now()
        msg_self.attachments = []
        
        mock_channel.history.return_value = AsyncIter([msg_self])
        
        await self.vm.trigger_thought_process()
        
        call_args = self.mock_get_response.call_args[0][0]
        user_msg = call_args[1]['content']
        
        self.assertIn("You (Nyx): My own words", user_msg)

if __name__ == '__main__':
    unittest.main()
