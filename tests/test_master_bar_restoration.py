import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import sys
import os
import datetime

sys.path.append(os.getcwd())

from NyxOS import LMStudioBot
import ui
import config

# Helper for async iteration
class AsyncIter:
    def __init__(self, items):
        self.items = list(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

class TestMasterBarRestoration:
    
    @pytest.mark.asyncio
    async def test_master_bar_populates_from_db_on_boot(self):
        """
        Verifies that the master bar message is populated with content 
        from the database during console initialization.
        """
        # Setup Mocks
        with patch('discord.Client.__init__'), \
             patch('discord.app_commands.CommandTree'), \
             patch('discord.Client.user', new_callable=PropertyMock) as mock_user, \
             patch('memory_manager.get_master_bar') as mock_get_master, \
             patch('memory_manager.get_bar_whitelist', return_value=[]), \
             patch('memory_manager.get_all_bars', return_value={}):
             
            mock_user.return_value = MagicMock(id=12345)
            
            # Mock DB return
            saved_master_content = "👑 The Master Bar Content 👑"
            mock_get_master.return_value = saved_master_content
            
            bot = LMStudioBot()
            bot.get_channel = MagicMock(return_value=None)
            bot.fetch_channel = AsyncMock()
            
            # Mock Channel
            mock_channel = AsyncMock()
            mock_channel.id = 999
            bot.fetch_channel.return_value = mock_channel
            
            # Case 1: Channel is empty (Simulate fresh boot/wipe)
            mock_channel.history = MagicMock(return_value=AsyncIter([]))
            
            # Mock purge
            mock_channel.purge = AsyncMock()
            
            # Mock send (returns a message object)
            async def mock_send_side_effect(content, view=None):
                msg = AsyncMock()
                msg.content = content
                msg.id = 100 + len(mock_channel.send.mock_calls)
                return msg
            mock_channel.send.side_effect = mock_send_side_effect
            
            # Execute the logic
            await bot.initialize_console_channel(mock_channel)
            
            # Verification
            # We expect 4 sends: Header, Master Bar, Uplinks List, Event Log
            assert mock_channel.send.call_count == 4
            
            # Check 2nd message (Master Bar)
            args, _ = mock_channel.send.call_args_list[1]
            sent_content = args[0]
            
            assert sent_content == saved_master_content
            assert bot.startup_bar_msg.content == saved_master_content
            
            # Case 2: Channel has messages (Update existing)
            # Reset calls
            mock_channel.send.reset_mock()
            mock_channel.purge.reset_mock()
            
            # Create 4 existing messages
            msg1 = MagicMock(author=MagicMock(id=12345), content="Old Header", created_at=datetime.datetime(2025, 1, 1, 10, 0, 0))
            msg1.edit = AsyncMock()
            
            msg2 = MagicMock(author=MagicMock(id=12345), content="Old Master Content", created_at=datetime.datetime(2025, 1, 1, 10, 0, 1))
            msg2.edit = AsyncMock()
            
            msg3 = MagicMock(author=MagicMock(id=12345), content="Old List", created_at=datetime.datetime(2025, 1, 1, 10, 0, 2))
            msg3.edit = AsyncMock()

            msg4 = MagicMock(author=MagicMock(id=12345), content=f"{ui.FLAVOR_TEXT['COSMETIC_DIVIDER']}\n# System Events", created_at=datetime.datetime(2025, 1, 1, 10, 0, 3))
            msg4.edit = AsyncMock()
            
            # Mock history to return these 4
            mock_channel.history = MagicMock(return_value=AsyncIter([msg1, msg2, msg3, msg4]))
            
            # Execute
            await bot.initialize_console_channel(mock_channel)
            
            # Verify NO wipe/send
            mock_channel.purge.assert_not_called()
            mock_channel.send.assert_not_called()
            
            # Verify Edit on msg2 (Master Bar)
            msg2.edit.assert_called_with(content=saved_master_content)
            assert bot.startup_bar_msg == msg2