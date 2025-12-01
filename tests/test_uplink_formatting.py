import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NyxOS
import ui

@pytest.mark.asyncio
class TestUplinkFormatting:
    async def test_uplink_grouping(self):
        client = NyxOS.LMStudioBot()
        client.active_bars = {}
        
        # Create 15 active bars
        whitelist = []
        for i in range(1, 16):
            cid = i
            client.active_bars[cid] = {
                "content": "Bar",
                "guild_id": 100,
                "message_id": 200,
                "checkmark_message_id": 200
            }
            whitelist.append(str(cid))
            
        # Mock memory_manager
        with patch('NyxOS.memory_manager') as mock_mem:
            mock_mem.get_bar_whitelist.return_value = whitelist
            mock_mem.get_master_bar.return_value = "Master"
            
            # Mock Discord objects
            mock_channel = AsyncMock()
            mock_channel.id = 999
            
            # Initial message
            msg1 = AsyncMock()
            msg1.channel = mock_channel
            msg1.content = "Old Content"
            
            client.console_progress_msgs = [msg1]
            
            # Mock Limiter
            client.active_views = {}
            with patch('NyxOS.services.service.limiter.wait_for_slot', AsyncMock()):
                await client.update_console_status()
                
            # Verify content
            # 15 items. 6 per line.
            # Line 1: 1..6
            # Line 2: 7..12
            # Line 3: 13..15
            
            assert len(client.console_progress_msgs) >= 1
            last_msg = client.console_progress_msgs[-1]
            content = last_msg.edit.call_args[1]['content']
            
            # Check for grouping
            # We expect the separator "  " to appear multiple times
            lines = content.split('\n')
            # Filter out header
            uplink_lines = [l for l in lines if "https://" in l or "<#" in l]
            
            assert len(uplink_lines) == 3
            assert uplink_lines[0].count("https://") == 6
            assert uplink_lines[1].count("https://") == 6
            assert uplink_lines[2].count("https://") == 3

    async def test_uplink_splitting(self):
        client = NyxOS.LMStudioBot()
        client.active_bars = {}
        
        # Create 200 active bars (Should exceed 2000 chars)
        # Each link is approx 60 chars. 200 * 60 = 12000 chars.
        # Should split into ~6 messages.
        whitelist = []
        for i in range(1, 201):
            cid = i
            client.active_bars[cid] = {
                "content": "Bar",
                "guild_id": 100,
                "message_id": 200,
                "checkmark_message_id": 200
            }
            whitelist.append(str(cid))
            
        with patch('NyxOS.memory_manager') as mock_mem:
            mock_mem.get_bar_whitelist.return_value = whitelist
            
            mock_channel = AsyncMock()
            mock_channel.id = 999
            
            msg1 = AsyncMock()
            msg1.channel = mock_channel
            msg1.content = "Old"
            
            client.console_progress_msgs = [msg1]
            
            # Mock Channel Send for new messages
            mock_channel.send.return_value = AsyncMock()
            
            with patch('NyxOS.services.service.limiter.wait_for_slot', AsyncMock()):
                await client.update_console_status()
                
            # Verify multiple messages
            assert len(client.console_progress_msgs) > 1
            # Verify edit called on first
            assert msg1.edit.called
            # Verify send called for others
            assert mock_channel.send.called
