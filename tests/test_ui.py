import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import ui
import config

class TestUI(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.interaction = MagicMock()
        self.interaction.response = MagicMock()
        self.interaction.response.send_message = AsyncMock()
        self.interaction.response.edit_message = AsyncMock()
        self.interaction.edit_original_response = AsyncMock()
        self.interaction.followup.send = AsyncMock()
        self.interaction.user.id = 123
        self.interaction.user.display_name = "TestUser"
        self.interaction.message.id = 555
        self.interaction.channel.id = 999
        self.interaction.client = MagicMock()
        self.interaction.client.good_bot_cooldowns = {}
        self.interaction.client.loop.create_task = MagicMock()
        
        # Mock config bug channel
        self.bug_patch = patch('ui.config.BUG_REPORT_CHANNEL_ID', 888)
        self.bug_patch.start()

        # Mock Services
        self.service_patch = patch('services.service')
        self.mock_service = self.service_patch.start()
        self.mock_service.query_lm_studio = AsyncMock(return_value="New Response")

    async def asyncTearDown(self):
        self.bug_patch.stop()
        self.service_patch.stop()

    # --- test_response_view_init ---
    async def test_response_view_init_debug_off(self):
        """Verify 'Debug' buttons are hidden when debug_mode is False."""
        with patch('ui.memory_manager.get_server_setting', return_value=False):
            view = ui.ResponseView()
            
            # Check if debug buttons exist
            debug_ids = ["debug_reboot_btn", "debug_shutdown_btn", "debug_test_btn"]
            found = [item.custom_id for item in view.children if item.custom_id in debug_ids]
            self.assertEqual(found, [], "Debug buttons found while debug_mode is False")

    async def test_response_view_init_debug_on(self):
        """Verify 'Debug' buttons appear when debug_mode is True."""
        with patch('ui.memory_manager.get_server_setting', return_value=True):
            view = ui.ResponseView()
            
            # Check if debug buttons exist
            debug_ids = ["debug_reboot_btn", "debug_shutdown_btn", "debug_test_btn"]
            found = [item.custom_id for item in view.children if item.custom_id in debug_ids]
            self.assertTrue(set(debug_ids).issubset(found), "Debug buttons missing while debug_mode is True")

    # --- test_retry_button ---
    async def test_retry_button(self):
        """
        Mock services.query_lm_studio.
        Verify clicking retry calls the service and edits the message.
        """
        # Setup View
        view = ui.ResponseView(
            original_prompt="Prompt", 
            user_id=123, 
            history_messages=[], 
            channel_obj=MagicMock()
        )
        
        # Find Retry Button
        retry_btn = [child for child in view.children if child.custom_id == "retry_btn"][0]
        
        # Trigger Callback directly on the view
        # Mock asyncio.sleep to speed up test
        with patch('asyncio.sleep', new=AsyncMock()):
            # Bypass Discord UI dispatch and call the underlying function directly
            # It appears to be stored as the raw function on the class
            await ui.ResponseView.retry_callback(view, self.interaction, retry_btn)
        
        # Verify Service Call
        self.mock_service.query_lm_studio.assert_called_once()
        
        # Verify Edit
        # It edits initially to "Thinking...", then updates countdown, then final text
        self.assertTrue(self.interaction.response.edit_message.called)
        self.assertTrue(self.interaction.edit_original_response.called)
        
        # Verify final content update
        call_args = self.interaction.edit_original_response.call_args_list
        
        # We expect at least one call with content="New Response"
        found_content = False
        for call in call_args:
            if 'content' in call.kwargs and call.kwargs['content'] == "New Response":
                found_content = True
                break
        self.assertTrue(found_content, "Did not find final response update")

    # --- test_bug_report_modal ---
    async def test_bug_report_modal(self):
        """
        Verify submission sends a message to the correct channel ID.
        """
        # Setup Modal
        modal = ui.BugReportModal("http://msg.url")
        # Set internal value for TextInputs
        modal.report_title._value = "Test Bug"
        modal.report_body._value = "This is a test bug description."
        
        # Mock Channel Fetch
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        
        # Mock Thread creation on the sent message
        mock_sent_msg = MagicMock()
        mock_sent_msg.create_thread = AsyncMock()
        mock_channel.send.return_value = mock_sent_msg
        
        self.interaction.client.get_channel.return_value = mock_channel
        
        # Trigger Submit
        await modal.on_submit(self.interaction)
        
        # Verify Channel Fetch (Config ID 888)
        self.interaction.client.get_channel.assert_called_with(888)
        
        # Verify Message Send
        mock_channel.send.assert_called()
        args = mock_channel.send.call_args[0][0]
        self.assertIn("Test Bug", args)
        
        # Verify Thread Creation
        mock_sent_msg.create_thread.assert_called()
        
        # Verify Response to user
        self.interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["BUG_REPORT_THANKS"], ephemeral=True)

if __name__ == '__main__':
    unittest.main()
