import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import ui

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock config before importing NyxOS
with patch.dict(os.environ, {"BOT_TOKEN": "test", "KAGI_API_TOKEN": "test"}):
    import NyxOS
    import memory_manager

class TestConsoleSync(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.client = NyxOS.LMStudioBot()
        self.client.active_bars = {}
        # Mock console progress msgs
        self.console_msg = AsyncMock()
        self.console_msg.channel.id = 999
        self.client.console_progress_msgs = [self.console_msg]
        
    async def test_idle_all_bars_updates_prefix(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "OldContent", 
                "user_id": 1, 
                "message_id": 10, 
                "checkmark_message_id": 10
            }
        }
        
        with patch('memory_manager.get_allowed_channels', return_value=[cid]), \
             patch('memory_manager.save_bar') as mock_save, \
             patch.object(self.client, 'get_channel', return_value=AsyncMock()) as mock_get_ch, \
             patch.object(self.client, 'update_console_status', new_callable=AsyncMock) as mock_update_console:
            
            mock_ch = mock_get_ch.return_value
            mock_msg = AsyncMock()
            mock_msg.id = 10
            mock_ch.fetch_message.return_value = mock_msg
            
            # Execute
            await self.client.idle_all_bars()
            
            # Verify active_bars update
            self.assertIn("current_prefix", self.client.active_bars[cid])
            idle_emoji = "<a:NotWatching:1301840196966285322>"
            self.assertEqual(self.client.active_bars[cid]["current_prefix"], idle_emoji)
            
            # Verify DB Save
            mock_save.assert_called()
            _, kwargs = mock_save.call_args
            self.assertEqual(kwargs.get('current_prefix'), idle_emoji)
            
            # Verify Console Sync Called
            mock_update_console.assert_called_once()

    async def test_update_console_status_uses_prefix(self):
        # Setup
        cid = 123
        test_emoji = "🧪"
        self.client.active_bars = {
            cid: {
                "content": "Content", 
                "user_id": 1, 
                "message_id": 10, 
                "current_prefix": test_emoji,
                "guild_id": 555
            }
        }
        
        with patch('memory_manager.get_bar_whitelist', return_value=[str(cid)]), \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Execute
            await self.client.update_console_status()
            
            # Verify Message Edit content
            self.console_msg.edit.assert_called()
            args, kwargs = self.console_msg.edit.call_args
            content = args[0] if args else kwargs.get('content')
            
            self.assertIn(test_emoji, content)
            self.assertIn(f"https://discord.com/channels/555/{cid}/10", content)

    async def test_update_console_status_default_prefix(self):
        # Setup (No current_prefix)
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Content", 
                "user_id": 1, 
                "message_id": 10,
                # Missing current_prefix
                "guild_id": 555
            }
        }
        
        with patch('memory_manager.get_bar_whitelist', return_value=[str(cid)]), \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Execute
            await self.client.update_console_status()
            
            # Verify Message Edit content uses default (Speed 0)
            self.console_msg.edit.assert_called()
            args, kwargs = self.console_msg.edit.call_args
            content = args[0] if args else kwargs.get('content')
            
            default_emoji = ui.BAR_PREFIX_EMOJIS[2]
            self.assertIn(default_emoji, content)
