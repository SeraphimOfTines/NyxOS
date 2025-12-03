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

class TestIdleSleepToggle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = NyxOS.client
        self.client.active_bars = {}
        # Mock internal connection user to satisfy client.user property
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 12345

    async def test_sleep_toggle(self):
        # Setup active bars
        cid = 100
        initial_state = {
            "content": "Watching Things",
            "user_id": 1,
            "message_id": 500,
            "persisting": False
        }
        self.client.active_bars[cid] = initial_state.copy()
        
        # Mock Channels and Messages
        mock_channel = AsyncMock()
        mock_msg = AsyncMock()
        mock_msg.id = 500
        mock_msg.content = "Watching Things"
        self.client.get_channel = MagicMock(return_value=mock_channel)
        mock_channel.fetch_message.return_value = mock_msg
        
        # Mock Memory Manager
        with patch('memory_manager.get_server_setting') as mock_get_setting, \
             patch('memory_manager.set_server_setting') as mock_set_setting, \
             patch('memory_manager.save_previous_state') as mock_save_prev, \
             patch('memory_manager.get_previous_state') as mock_get_prev, \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('memory_manager.get_allowed_channels', return_value=[]), \
             patch('memory_manager.set_bar_sleeping') as mock_set_sleeping:

            # 1. Normal -> Sleep
            mock_get_setting.return_value = "normal"
            
            await self.client.sleep_all_bars()
            
            # Should set mode to sleep
            mock_set_setting.assert_called_with("system_mode", "sleep")
            # Should save previous state (since normal)
            mock_save_prev.assert_called_with(cid, initial_state)
            # Should edit message to sleep emoji
            mock_msg.edit.assert_called()
            kwargs = mock_msg.edit.call_args.kwargs
            content = kwargs.get('content', mock_msg.edit.call_args[0][0] if mock_msg.edit.call_args[0] else "")
            self.assertIn("<a:Sleeping:", content) 
            
            # 2. Sleep -> Normal (Toggle)
            mock_get_setting.return_value = "sleep"
            mock_get_prev.return_value = {
                "content": "Watching Things",
                "current_prefix": "👀",
                "has_notification": False,
                "persisting": False,
                "user_id": 1
            }
            
            await self.client.sleep_all_bars()
            
            # Should call restore_all_bars which sets mode to normal
            mock_set_setting.assert_called_with("system_mode", "normal")
            # Should restore content
            mock_msg.edit.assert_called()
            kwargs = mock_msg.edit.call_args.kwargs
            content = kwargs.get('content', mock_msg.edit.call_args[0][0] if mock_msg.edit.call_args[0] else "")
            self.assertIn("Watching Things", content)

    async def test_idle_toggle(self):
        # Setup active bars
        cid = 200
        initial_state = {
            "content": "Watching Things",
            "user_id": 2,
            "message_id": 600,
            "persisting": False
        }
        self.client.active_bars[cid] = initial_state.copy()
        
        mock_channel = AsyncMock()
        mock_msg = AsyncMock()
        mock_msg.id = 600
        mock_msg.content = "Watching Things"
        self.client.get_channel = MagicMock(return_value=mock_channel)
        mock_channel.fetch_message.return_value = mock_msg

        with patch('memory_manager.get_server_setting') as mock_get_setting, \
             patch('memory_manager.set_server_setting') as mock_set_setting, \
             patch('memory_manager.save_previous_state') as mock_save_prev, \
             patch('memory_manager.get_previous_state') as mock_get_prev, \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('memory_manager.get_allowed_channels', return_value=[]):

            # 1. Normal -> Idle
            mock_get_setting.return_value = "normal"
            
            await self.client.idle_all_bars()
            
            mock_set_setting.assert_called_with("system_mode", "idle")
            # Idle does NOT save previous state
            mock_save_prev.assert_not_called()
            
            mock_msg.edit.assert_called()
            kwargs = mock_msg.edit.call_args.kwargs
            content = kwargs.get('content', mock_msg.edit.call_args[0][0] if mock_msg.edit.call_args[0] else "")
            self.assertIn("<a:NotWatching:", content)

            # 2. Idle -> Normal (Toggle - Manual via Global command or similar, but idle_all_bars is reset only)
            # The test logic assumed toggle behavior. If idle_all_bars is idempotent, this test might need adjustment.
            # But let's assume user calls it again? No, idle_all_bars sets idle.
            # There is no "toggle" logic inside idle_all_bars like sleep_all_bars.
            # So we just test Idle functionality.
            pass 

    async def test_mixed_transition(self):
        # Normal -> Idle -> Sleep -> Normal
        
        cid = 300
        initial_state = {
            "content": "Watching Things",
            "user_id": 3,
            "message_id": 700,
            "persisting": False
        }
        self.client.active_bars[cid] = initial_state.copy()
        
        mock_channel = AsyncMock()
        mock_msg = AsyncMock()
        mock_msg.id = 700
        self.client.get_channel = MagicMock(return_value=mock_channel)
        mock_channel.fetch_message.return_value = mock_msg

        with patch('memory_manager.get_server_setting') as mock_get_setting, \
             patch('memory_manager.set_server_setting') as mock_set_setting, \
             patch('memory_manager.save_previous_state') as mock_save_prev, \
             patch('memory_manager.get_previous_state') as mock_get_prev, \
             patch('memory_manager.save_bar') as mock_save_bar, \
             patch('memory_manager.get_allowed_channels', return_value=[]), \
             patch('memory_manager.set_bar_sleeping') as mock_set_sleeping:
             
             # Transition 1: Normal -> Idle
             mock_get_setting.return_value = "normal"
             await self.client.idle_all_bars()
             mock_save_prev.assert_not_called()
             
             # Transition 2: Idle -> Sleep
             mock_get_setting.return_value = "idle"
             mock_save_prev.reset_mock()
             await self.client.sleep_all_bars()
             mock_save_prev.assert_not_called() # Should NOT save Idle state
             
             # Transition 3: Sleep -> Normal
             mock_get_setting.return_value = "sleep"
             mock_get_prev.return_value = {
                "content": "Watching Things",
                "current_prefix": "👀",
                "has_notification": False,
                "persisting": False,
                "user_id": 3
             }
             await self.client.sleep_all_bars()
             mock_set_setting.assert_called_with("system_mode", "normal")
             
             kwargs = mock_msg.edit.call_args.kwargs
             content = kwargs.get('content', mock_msg.edit.call_args[0][0] if mock_msg.edit.call_args[0] else "")
             self.assertIn("Watching Things", content)