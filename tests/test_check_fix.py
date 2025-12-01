import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NyxOS
import ui

@pytest.mark.asyncio
class TestCheckFix:
    async def test_drop_check_already_merged(self):
        client = NyxOS.LMStudioBot()
        cid = 123
        
        # Case: Checkmark IS merged (same IDs)
        client.active_bars = {
            cid: {
                "content": "Bar",
                "user_id": 1,
                "message_id": 100,
                "checkmark_message_id": 100, # Merged
                "persisting": False
            }
        }
        
        mock_channel = AsyncMock()
        client.get_channel = MagicMock(return_value=mock_channel)
        
        # We expect NOTHING to happen (no edit, no delete)
        # Because move_bar=False and check is merged.
        
        await client.drop_status_bar(cid, move_bar=False, move_check=True)
        
        # Verify NO edits or deletes on messages
        # We can't easily check "no calls" on everything, but we can check critical ones.
        # drop_status_bar normally calls channel.fetch_message and edit/delete.
        
        # With our fix, it should set move_check=False.
        # Then fall through to DB save.
        # It shouldn't try to fetch old check message to delete it.
        
        # Mock fetch_message to fail if called, or track calls
        mock_channel.fetch_message = AsyncMock()
        
        # Re-run with mock
        await client.drop_status_bar(cid, move_bar=False, move_check=True)
        
        # Assert fetch_message might be called (it fetches old bar if not moving)
        # But CRITICALLY, verify that DELETE or EDIT were NOT called on the returned message.
        
        # Check calls on the returned mock from fetch_message
        # Since we didn't set a specific return value for the second run, it returns a new AsyncMock.
        # We need to capture it or set it.
        
        # Reset mock and set return
        mock_channel.fetch_message.reset_mock()
        mock_msg = AsyncMock()
        mock_channel.fetch_message.return_value = mock_msg
        
        await client.drop_status_bar(cid, move_bar=False, move_check=True)
        
        # Verify no mutation
        mock_msg.edit.assert_not_called()
        mock_msg.delete.assert_not_called()

    async def test_drop_check_not_merged(self):
        client = NyxOS.LMStudioBot()
        cid = 123
        
        # Case: Checkmark is NOT merged
        client.active_bars = {
            cid: {
                "content": "Bar",
                "user_id": 1,
                "message_id": 100,
                "checkmark_message_id": 101, # Different
                "persisting": False
            }
        }
        
        mock_channel = AsyncMock()
        client.get_channel = MagicMock(return_value=mock_channel)
        
        mock_msg_101 = AsyncMock()
        mock_msg_100 = AsyncMock()
        
        async def fetch_side_effect(mid):
            if mid == 100: return mock_msg_100
            if mid == 101: return mock_msg_101
            return None
        mock_channel.fetch_message.side_effect = fetch_side_effect
        
        # Mock Limiter
        with patch('NyxOS.services.service.limiter.wait_for_slot', AsyncMock()):
            await client.drop_status_bar(cid, move_bar=False, move_check=True)
            
        # Should fetch 101 (to delete/edit) and 100 (target)
        assert mock_channel.fetch_message.call_count >= 1
        # 101 should be deleted or edited (logic says delete old check if different)
        mock_msg_101.delete.assert_called_once()
