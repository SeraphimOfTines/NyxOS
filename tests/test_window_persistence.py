import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.getcwd())

from NyxOS import LMStudioBot
import ui

class TestWindowPersistence:
    
    @pytest.mark.asyncio
    async def test_view_persistence_across_reboot(self):
        """
        Simulates a reboot scenario:
        1. 'DB' returns active bars.
        2. Bot runs restore_status_bar_views().
        3. Verify views are re-attached to specific message IDs.
        """
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=MagicMock) as mock_user:
             
            mock_user.id = 12345
            bot = LMStudioBot()
            
            # Mock Active Bars (as if loaded from DB)
            # Note: The 'active_bars' dict structure now includes checkmark_message_id
            bot.active_bars = {
                1001: {
                    "channel_id": 1001,
                    "message_id": 5001,
                    "checkmark_message_id": 5002,
                    "user_id": 999,
                    "content": "<a:Speed1:> Bar Content",
                    "persisting": True,
                    "current_prefix": "<a:Speed1:>",
                    "has_notification": False
                },
                1002: {
                    "channel_id": 1002,
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
            
            # Execute Restore
            bot.restore_status_bar_views()
            
            # Verify
            assert bot.add_view.call_count == 2
            
            # Check Call 1 (Channel 1001)
            # Note: Python dicts are ordered since 3.7, so 1001 should be first.
            args1, kwargs1 = bot.add_view.call_args_list[0]
            view1 = args1[0]
            
            assert isinstance(view1, ui.StatusBarView)
            assert kwargs1['message_id'] == 5001 # Crucial: Attached to correct message
            assert view1.channel_id == 1001
            assert view1.persisting is True
            assert view1.original_user_id == 999
            
            # Check Call 2 (Channel 1002)
            args2, kwargs2 = bot.add_view.call_args_list[1]
            view2 = args2[0]
            
            assert isinstance(view2, ui.StatusBarView)
            assert kwargs2['message_id'] == 6001
            assert view2.channel_id == 1002
            assert view2.persisting is False
            
            print("✅ Persistence Test Passed: Views re-attached correctly.")
