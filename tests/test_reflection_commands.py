import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import command_handler
import ui

class TestReflectionCommands:
    @pytest.fixture
    def mock_client(self):
        return MagicMock()

    @pytest.fixture
    def mock_message(self):
        msg = MagicMock()
        msg.content = ""
        msg.channel.send = AsyncMock()
        msg.author.id = 999
        msg.webhook_id = None
        return msg

    @pytest.mark.asyncio
    async def test_reflect_command(self, mock_client, mock_message):
        mock_message.content = "&reflect"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('command_handler.self_reflection.generate_daily_reflection', new_callable=AsyncMock) as mock_gen:
            
            mock_gen.return_value = "Today was a good day."
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            mock_gen.assert_called_once()
            # Verify the response was sent (might be multiple calls, check any)
            # The first call is "Thinking...", second is result
            calls = mock_message.channel.send.call_args_list
            assert any("Today was a good day." in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_reflect_command_unauthorized(self, mock_client, mock_message):
        mock_message.content = "&reflect"
        
        with patch('helpers.is_authorized', return_value=False):
            await command_handler.handle_prefix_command(mock_client, mock_message)
            mock_message.channel.send.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])

    @pytest.mark.asyncio
    async def test_debugreflect_command(self, mock_client, mock_message):
        mock_message.content = "&debugreflect"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('command_handler.self_reflection.run_nightly_prompt_update', new_callable=AsyncMock) as mock_run:
            
            mock_run.return_value = "New Prompt"
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            mock_run.assert_called_once()
            calls = mock_message.channel.send.call_args_list
            assert any("Cycle Complete" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_debugreflect_command_failure(self, mock_client, mock_message):
        mock_message.content = "&debugreflect"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('command_handler.self_reflection.run_nightly_prompt_update', new_callable=AsyncMock) as mock_run:
            
            mock_run.side_effect = Exception("Boom")
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            calls = mock_message.channel.send.call_args_list
            assert any("Cycle Failed" in str(c) for c in calls)
