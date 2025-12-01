import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import ui

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_utils import AsyncIter

# Mock config before importing NyxOS
with patch.dict(os.environ, {"BOT_TOKEN": "test", "KAGI_API_TOKEN": "test"}):
    import NyxOS
    import memory_manager

class TestConsoleNotification(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.client = NyxOS.LMStudioBot()
        # Mock internal connection user for the property 'user'
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 999 
        self.client._connection.user.display_name = "NyxOS"
        
        self.client.active_bars = {}
        
        # Mock console progress msgs
        self.console_msg = AsyncMock()
        self.console_msg.channel.id = 888
        self.client.console_progress_msgs = [self.console_msg]
        
    async def test_on_message_triggers_notification(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 10, 
                "has_notification": False,
                "persisting": False
            }
        }
        
        message = AsyncMock()
        message.channel.id = cid
        message.author.id = 456 # Not Bot
        message.webhook_id = None
        message.content = "Hello"
        message.reference = None
        # Mock history
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        # Patch the global 'client' in NyxOS with our test instance
        with patch('NyxOS.client', self.client):
            with patch('memory_manager.set_bar_notification') as mock_set_db, \
                 patch.object(self.client, 'update_console_status', new_callable=AsyncMock) as mock_update_console, \
                 patch('memory_manager.get_server_setting', return_value=False), \
                 patch('helpers.matches_proxy_tag', return_value=False):
                
                # Execute the module-level function
                await NyxOS.on_message(message)
                
                # Verify State Update
                self.assertTrue(self.client.active_bars[cid]["has_notification"])
                
                # Verify DB Call
                mock_set_db.assert_called_with(cid, True)
                
                # Verify Console Update
                mock_update_console.assert_called()
                
    async def test_subsequent_messages_do_not_trigger_update(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 10, 
                "has_notification": False,
                "persisting": False
            }
        }
        
        message = AsyncMock()
        message.channel.id = cid
        message.author.id = 456 
        message.webhook_id = None
        message.content = "Msg 1"
        message.reference = None
        # Mock history
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        with patch('NyxOS.client', self.client):
            with patch('memory_manager.set_bar_notification') as mock_set_db, \
                 patch.object(self.client, 'update_console_status', new_callable=AsyncMock) as mock_update_console, \
                 patch('memory_manager.get_server_setting', return_value=False), \
                 patch('helpers.matches_proxy_tag', return_value=False):
                
                # 1. First Message
                await NyxOS.on_message(message)
                mock_update_console.assert_called_once()
                self.assertTrue(self.client.active_bars[cid]["has_notification"])
                
                # Reset Mock
                mock_update_console.reset_mock()
                
                # 2. Second Message
                message.content = "Msg 2"
                await NyxOS.on_message(message)
                
                # Should NOT be called again
                mock_update_console.assert_not_called()

    async def test_drop_notification_logic(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 10, 
                "has_notification": True, # Already notified
                "persisting": False
            }
        }
        
        with patch('memory_manager.set_bar_notification') as mock_set_db, \
             patch('memory_manager.save_bar'), \
             patch('memory_manager.save_channel_location'), \
             patch.object(self.client, 'get_channel', return_value=AsyncMock()) as mock_get_ch, \
             patch.object(self.client, 'update_console_status', new_callable=AsyncMock):
             
            mock_ch = mock_get_ch.return_value
            mock_ch.send = AsyncMock()
            mock_msg = AsyncMock()
            mock_msg.id = 99
            mock_ch.send.return_value = mock_msg
            # Mock history
            mock_ch.history = MagicMock(return_value=AsyncIter([]))
            
            # 1. Manual Drop (Default) -> Should Clear
            await self.client.drop_status_bar(cid)
            self.assertFalse(self.client.active_bars[cid]["has_notification"])
            mock_set_db.assert_called_with(cid, False)
            
            # Reset
            self.client.active_bars[cid]["has_notification"] = True
            mock_set_db.reset_mock()
            
            # 2. Auto Drop (manual=False) -> Should Persist
            await self.client.drop_status_bar(cid, manual=False)
            self.assertTrue(self.client.active_bars[cid]["has_notification"])
            mock_set_db.assert_not_called()

    async def test_update_console_renders_exclamark(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 10, 
                "guild_id": 555,
                "has_notification": True # True
            }
        }
        
        with patch('memory_manager.get_bar_whitelist', return_value=[str(cid)]), \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Execute
            await self.client.update_console_status()
            
            # Verify
            self.console_msg.edit.assert_called()
            args, kwargs = self.console_msg.edit.call_args
            content = args[0] if args else kwargs.get('content')
            
            exclamark = "<a:SeraphExclamark:1317628268299554877>"
            self.assertIn(exclamark, content)
            self.assertNotIn("(Out of sync.)", content)

    async def test_update_console_no_exclamark_when_false(self):
        # Setup
        cid = 123
        self.client.active_bars = {
            cid: {
                "content": "Bar", 
                "user_id": 1, 
                "message_id": 10, 
                "guild_id": 555,
                "has_notification": False # False
            }
        }
        
        with patch('memory_manager.get_bar_whitelist', return_value=[str(cid)]), \
             patch('services.service.limiter.wait_for_slot', new=AsyncMock()):
            
            # Execute
            await self.client.update_console_status()
            
            # Verify
            self.console_msg.edit.assert_called()
            args, kwargs = self.console_msg.edit.call_args
            content = args[0] if args else kwargs.get('content')
            
            exclamark = "<a:SeraphExclamark:1317628268299554877>"
            self.assertNotIn(exclamark, content)
            self.assertNotIn("(Out of sync.)", content)
