import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import asyncio

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import ui
import config

class TestWakeupLogic(unittest.IsolatedAsyncioTestCase):
    
    async def test_on_ready_wakeup(self):
        # 1. Setup Mocks
        with patch('discord.Client.user', new_callable=MagicMock) as mock_user_prop:
            mock_user = MagicMock()
            mock_user.id = 12345
            mock_user_prop.__get__ = MagicMock(return_value=mock_user)
            
            client = NyxOS.LMStudioBot()
            # Client user is accessed via self.user which delegates to the property
            # We need to ensure client.user returns our mock_user
            
            client.check_and_sync_commands = AsyncMock()
            client.wait_until_ready = AsyncMock()
            client.is_closed = MagicMock(return_value=False)
            client.loop = MagicMock()
            
            # Mock Channel
            channel = MagicMock()
            channel.id = 999
            channel.name = "test-channel"
            
            # Mock History (Async Iterator)
            # Create a mock message that looks like a bar
            bar_msg = MagicMock()
            bar_msg.author.id = 12345
            bar_msg.content = f"{ui.BAR_PREFIX_EMOJIS[0]} Status Bar Content {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
            
            async def mock_history(limit=50):
                yield bar_msg
                
            channel.history = MagicMock(side_effect=mock_history)
            channel.send = AsyncMock(return_value=MagicMock(id=555))
            
            client.get_channel = MagicMock(return_value=channel)
            
            # Mock Dependencies
            with patch('memory_manager.get_allowed_channels', return_value=[999]), \
                 patch('memory_manager.get_bar_whitelist', return_value=[999]), \
                 patch('memory_manager.get_all_bars', return_value={}), \
                 patch('memory_manager.save_bar') as mock_save, \
                 patch('memory_manager.get_channel_location', return_value=(None, None)), \
                 patch('memory_manager.save_channel_location') as mock_save_loc, \
                 patch('asyncio.sleep', new=AsyncMock()), \
                 patch.object(client, 'wipe_channel_bars', new=AsyncMock()) as mock_wipe:
                
                # 2. Run perform_system_scan
                # We simulate DB lookup failure (return None, None above) to trigger fallback scan
                await client.perform_system_scan()
                
                # 3. Verifications
                
                # Verify Scan Limit (Fallback triggered)
                channel.history.assert_called_with(limit=5) # Updated limit to 5 based on new logic
                
                # Verify Save
                # Should have found bar and saved it
                mock_save_loc.assert_called()
                
                # Verify Wipe Called
                # Wipe is NOT called if we found/restored it
                mock_wipe.assert_not_called()
                
                # Verify we did NOT send a new message (since we found one)
                channel.send.assert_not_called()
                
                # Verify Persistence Capture (Default False since no DB entry)
                mock_save.assert_called()
                # args: channel_id, guild_id, msg_id, user_id, content, persisting
                save_args = mock_save.call_args[0]
                self.assertEqual(save_args[5], False)

if __name__ == '__main__':
    unittest.main()