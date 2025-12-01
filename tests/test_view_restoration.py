import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import discord
import sys
import os

# Ensure we can import from root
sys.path.append(os.getcwd())

# Import the class to test
from NyxOS import LMStudioBot
import ui

class TestViewRestoration:
    
    @pytest.mark.asyncio
    async def test_restore_status_bar_views(self):
        # 1. Initialize Bot (Mocking super init to avoid connection logic)
        from unittest.mock import PropertyMock
        
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=PropertyMock) as mock_user:
             
            mock_user.return_value = MagicMock(id=999)
            bot = LMStudioBot()
            
            # 2. Mock dependencies
            bot.active_bars = {
                101: {
                    "content": "Bar 1",
                    "user_id": 1,
                    "message_id": 5001,
                    "persisting": True
                },
                102: {
                    "content": "Bar 2",
                    "user_id": 2,
                    "message_id": 5002,
                    "persisting": False
                }
            }
            # Mock add_view (the crucial method we are testing)
            bot.add_view = MagicMock()
            # Mock internal registration
            bot._register_view = MagicMock()
            
            # 3. Run the method
            bot.restore_status_bar_views()
            
            # 4. Assertions
            assert bot.add_view.call_count == 2, "Should have called add_view twice"
            
            calls = bot.add_view.call_args_list
            
            # Check first call
            args1, kwargs1 = calls[0]
            view1 = args1[0]
            assert isinstance(view1, ui.StatusBarView)
            assert kwargs1['message_id'] == 5001
            assert view1.persisting is True
            assert view1.channel_id == 101
            
            # Check second call
            args2, kwargs2 = calls[1]
            view2 = args2[0]
            assert isinstance(view2, ui.StatusBarView)
            assert kwargs2['message_id'] == 5002
            assert view2.persisting is False
            assert view2.channel_id == 102