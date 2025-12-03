import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.mock_utils import AsyncIter
from NyxOS import LMStudioBot
import ui

class TestWindowPersistence:
    
    @pytest.mark.asyncio
    async def test_view_persistence_across_reboot(self):
        """
        Simulates a reboot scenario:
        1. 'DB' returns active bars.
        2. Bot runs verify_and_restore_bars().
        3. Verify views are re-attached to specific message IDs.
        """
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=MagicMock) as mock_user:
             
            mock_user.id = 12345
            bot = LMStudioBot()
            
            # Mock Active Bars (as if loaded from DB)
            bot.active_bars = {
                123456789012345678: {
                    "channel_id": 123456789012345678,
                    "message_id": 5001,
                    "checkmark_message_id": 5002,
                    "user_id": 999,
                    "content": "<a:Speed1:> Bar Content",
                    "persisting": True,
                    "current_prefix": "<a:Speed1:>",
                    "has_notification": False
                },
                123456789012345679: {
                    "channel_id": 123456789012345679,
                    "message_id": 6001,
                    # checkmark merged
                    "checkmark_message_id": 6001, 
                    "user_id": 888,
                    "content": "<a:Speed0:> Idle Bar",
                    "persisting": False,
                    "current_prefix": "<a:Speed0:>",
                    "has_notification": True
                }
            }
            
            # Mock methods
            bot.add_view = MagicMock()
            bot._register_view = MagicMock()
            bot.get_channel = MagicMock()
            
            # Mock Channel/Message Fetch
            mock_channel = AsyncMock()
            mock_channel.history = MagicMock(return_value=AsyncIter([]))
            mock_message = AsyncMock()
            mock_channel.fetch_message.return_value = mock_message
            bot.get_channel.return_value = mock_channel
            
            # Execute Restore (Async now)
            await bot.verify_and_restore_bars()
            
            # Verify
            assert bot.add_view.call_count == 2
            
            # Check Call 1 (Channel 1001)
            # Order isn't guaranteed in dict iteration usually, but often consistent in Py3.7+
            # Let's find them by ID
            calls = bot.add_view.call_args_list
            
            # Helper to find call by message_id
            def find_call(msg_id):
                for args, kwargs in calls:
                    if kwargs['message_id'] == msg_id:
                        return args[0], kwargs
                return None, None

            view1, kwargs1 = find_call(5001)
            assert view1 is not None
            assert isinstance(view1, ui.StatusBarView)
            assert kwargs1['message_id'] == 5001 
            assert view1.channel_id == 123456789012345678
            assert view1.persisting is True
            assert view1.original_user_id == 999
            
            view2, kwargs2 = find_call(6001)
            assert view2 is not None
            assert isinstance(view2, ui.StatusBarView)
            assert kwargs2['message_id'] == 6001
            assert view2.channel_id == 123456789012345679
            assert view2.persisting is False
            
            print("✅ Persistence Test Passed: Views re-attached correctly.")
