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
    async def test_verify_and_restore_bars(self):
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
                },
                103: { # Broken/Missing Bar
                    "content": "Bar 3",
                    "user_id": 3,
                    "message_id": 5003,
                    "persisting": True
                }
            }
            
            # Mock Channel/Message fetching
            mock_channel = AsyncMock()
            mock_message = AsyncMock()
            mock_channel.fetch_message.return_value = mock_message
            
            # Setup fetch_message to raise NotFound for 5003
            async def fetch_message_side_effect(msg_id):
                if msg_id == 5003:
                    raise discord.NotFound(MagicMock(), "Not Found")
                return mock_message
            
            mock_channel.fetch_message.side_effect = fetch_message_side_effect
            
            bot.get_channel = MagicMock(return_value=mock_channel)
            
            # Mock add_view
            bot.add_view = MagicMock()
            # Mock internal registration
            bot._register_view = MagicMock()
            
            # Mock DB deletion for cleanup
            with patch('memory_manager.delete_bar') as mock_delete, \
                 patch('memory_manager.remove_bar_whitelist') as mock_whitelist:
            
                # 3. Run the method
                await bot.verify_and_restore_bars()
                
                # 4. Assertions
                
                # Only 2 views should be restored (101 and 102)
                assert bot.add_view.call_count == 2, "Should have called add_view twice"
                
                # Verify calls
                calls = bot.add_view.call_args_list
                
                # 101
                args1, kwargs1 = calls[0]
                view1 = args1[0]
                assert kwargs1['message_id'] == 5001
                assert view1.persisting is True
                
                # 102
                args2, kwargs2 = calls[1]
                view2 = args2[0]
                assert kwargs2['message_id'] == 5002
                assert view2.persisting is False
                
                # Verify cleanup of 103
                mock_delete.assert_called_once_with(103)
                assert 103 not in bot.active_bars
