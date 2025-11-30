import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import ui
import discord
import config

class TestUI:
    
    @pytest.fixture
    def mock_interaction(self):
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.client.get_channel.return_value = MagicMock()
        interaction.user.id = 123
        interaction.message.id = 999
        interaction.channel.id = 100
        return interaction

    def test_response_view_init_debug_off(self):
        with patch('memory_manager.get_server_setting', return_value=False), \
             patch('asyncio.get_running_loop'):
            view = ui.ResponseView()
            # Check button labels
            labels = [child.label for child in view.children if hasattr(child, 'label')] 
            assert "🔄 Reboot" not in labels
            assert "🗑️" in labels # Delete button

    def test_response_view_init_debug_on(self):
        with patch('memory_manager.get_server_setting', return_value=True), \
             patch('asyncio.get_running_loop'):
            view = ui.ResponseView()
            labels = [child.label for child in view.children if hasattr(child, 'label')] 
            assert "🔄 Reboot" in labels
            assert "🛑 Shutdown" in labels

    @pytest.mark.asyncio
    async def test_retry_button(self, mock_interaction):
        with patch('asyncio.get_running_loop'):
            view = ui.ResponseView("Prompt", 123, "User", "", [], MagicMock())
        
        # Find retry button
        retry_btn = next(c for c in view.children if getattr(c, "custom_id", "") == "retry_btn")
        
        with patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query, \
             patch('asyncio.sleep', new_callable=AsyncMock): # Skip sleep
            
            mock_query.return_value = "Regenerated Content"
            
            # Call callback on the button item itself
            await retry_btn.callback(mock_interaction)
            
            assert mock_query.called
            
            mock_interaction.edit_original_response.assert_any_call(content="Regenerated Content", view=view)

    @pytest.mark.asyncio
    async def test_bug_report_modal(self, mock_interaction):
        modal = ui.BugReportModal("http://msg", 111, 222)
        modal.report_title = MagicMock()
        modal.report_title.value = "Bug Title"
        modal.report_body = MagicMock()
        modal.report_body.value = "Bug Body"
        
        mock_bug_channel = AsyncMock()
        mock_bug_msg = AsyncMock()
        mock_thread = AsyncMock()
        
        mock_bug_channel.send.return_value = mock_bug_msg
        mock_bug_msg.create_thread.return_value = mock_thread
        
        mock_interaction.client.get_channel.return_value = mock_bug_channel
        
        with patch('config.BUG_REPORT_CHANNEL_ID', 999):
             await modal.on_submit(mock_interaction)
             
             mock_bug_channel.send.assert_called()
             assert "Bug Title" in mock_bug_channel.send.call_args[0][0]
             mock_thread.send.assert_called() # Embed sent