import pytest
import discord
from unittest.mock import MagicMock, AsyncMock, patch
import NyxOS
import services

@pytest.mark.asyncio
async def test_ghost_check_logic_ghosted():
    """Verify on_message ignores ghosted (deleted) messages from systems."""
    client = NyxOS.client
    # Mock Client User (Best effort, but we mock volition to be safe)
    client._user = MagicMock()
    client._user.id = 999999
    client.volition.update_buffer = AsyncMock()
    
    # Mock Message
    message = MagicMock(spec=discord.Message)
    message.id = 999
    message.webhook_id = None
    message.author.id = 123
    message.author.bot = False
    message.content = "Test Message"
    message.channel = MagicMock()
    message.channel.id = 456
    message.guild = MagicMock()
    message.mentions = [client.user] # Trigger should_respond
    
    # Mock Services
    with patch('services.service.check_local_pk_system', new_callable=AsyncMock) as mock_check:
        mock_check.return_value = True # Is System
        
        # Mock Fetch Message to raise NotFound (Ghosted)
        message.channel.fetch_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "msg"))
        
        # Mock Sleep to run fast
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # We also need to mock processing_locks to avoid errors in finally block if we return early
            client.processing_locks = set()
            
            # Run on_message
            await client.on_message(message)
            
            # Assertions
            mock_sleep.assert_called_with(1.0)
            message.channel.fetch_message.assert_called_with(999)
            # Should NOT add to processing locks if returned early
            assert 999 not in client.processing_locks
            # Should NOT have typed
            message.channel.typing.assert_not_called()

@pytest.mark.asyncio
async def test_ghost_check_logic_survived():
    client = NyxOS.client
    # Mock Client User (Best effort, but we mock volition to be safe)
    client._user = MagicMock()
    client._user.id = 999999
    client.volition.update_buffer = AsyncMock()
    
    # Mock Message
    message = MagicMock(spec=discord.Message)
    message.id = 888
    message.webhook_id = None
    message.author.id = 123
    message.author.bot = False
    message.content = "Real Message"
    message.channel = MagicMock()
    message.channel.id = 456
    message.mentions = [client.user] # Trigger response
    
    # Mock Services
    with patch('services.service.check_local_pk_system', new_callable=AsyncMock) as mock_check:
        mock_check.return_value = True # Is System
        
        # Mock Fetch Message to succeed (Survives)
        message.channel.fetch_message = AsyncMock(return_value=message)
        
        # Mock Sleep
        with patch('asyncio.sleep', new_callable=AsyncMock):
             # Mock the rest of the pipeline to avoid deep execution errors
             with patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query:
                 # Mock typing context manager
                 message.channel.typing.return_value.__aenter__.return_value = None
                 
                 await client.on_message(message)
                 
                 # Should have proceeded to query (or at least lock)
                 # Since we mocked query, check if it was called?
                 # Wait, on_message calls command_handler first.
                 # Mock command handler
                 with patch('command_handler.handle_prefix_command', new_callable=AsyncMock) as mock_cmd:
                     mock_cmd.return_value = False
                     
                     # Re-run with command handler mocked
                     await client.on_message(message)
                     
                     # Check fetch was called
                     message.channel.fetch_message.assert_called_with(888)
