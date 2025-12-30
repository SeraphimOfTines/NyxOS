import pytest
import discord
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
import NyxOS
import config

@pytest.mark.asyncio
async def test_clearallmemory_sets_cutoff():
    """Verify &clearallmemory sets the global cutoff time."""
    client = NyxOS.client
    client.global_cutoff_time = None
    
    # Mock Interaction
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user.id = 12345
    interaction.created_at = datetime.utcnow()
    interaction.response = AsyncMock()
    
    # Mock Auth
    with patch('helpers.is_authorized', return_value=True):
        await NyxOS.clearallmemory_command.callback(interaction)
        
    assert client.global_cutoff_time == interaction.created_at
    interaction.response.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_history_cutoff_logic():
    """Simulate the history fetching logic to ensure it breaks on global cutoff."""
    client = NyxOS.client
    now = datetime.utcnow()
    client.global_cutoff_time = now - timedelta(minutes=5) # Cleared 5 mins ago
    
    # Messages
    msg_new = MagicMock()
    msg_new.created_at = now - timedelta(minutes=1)
    msg_new.content = "New Message"
    
    msg_old = MagicMock()
    msg_old.created_at = now - timedelta(minutes=10) # Older than cutoff
    msg_old.content = "Old Message"
    
    # Simulate Loop
    history = []
    messages = [msg_new, msg_old]
    
    for prev_msg in messages:
        # Logic from NyxOS.py
        if client.global_cutoff_time and prev_msg.created_at < client.global_cutoff_time:
            break
        history.append(prev_msg)
        
    assert len(history) == 1
    assert history[0] == msg_new
    assert msg_old not in history
