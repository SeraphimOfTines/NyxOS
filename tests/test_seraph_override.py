import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import command_handler
import ui
import config

class TestSeraphOverride(unittest.IsolatedAsyncioTestCase):
    async def test_seraph_override_success(self):
        """Test that '⛩ Seraphim ⛩' tag overrides authorization check."""
        
        # Mock Client
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        
        # Mock Message (Webhook + Seraph Tag)
        mock_message = MagicMock()
        mock_message.content = "&debug"
        mock_message.webhook_id = 12345
        mock_message.author.display_name = f"Sarah [{config.SERAPHIM_SYSTEM_TAG}]"
        mock_message.channel.send = AsyncMock()
        
        # Mock PK Data (Return None/Non-Admin ID)
        # We mock get_pk_message_data to return a random non-admin ID or None
        # pk_data = (name, sys_id, sys_name, tag, sender_id, desc)
        mock_pk_data = ("Sarah", "sys1", "System", "S", "999999", "Desc") # 999999 is NOT admin
        
        with patch('services.service.get_pk_message_data', new_callable=AsyncMock) as mock_get_pk, \
             patch('helpers.is_authorized', return_value=False) as mock_auth, \
             patch('memory_manager.get_server_setting', return_value=False), \
             patch('memory_manager.set_server_setting'):
            
            mock_get_pk.return_value = mock_pk_data
            
            # Execute
            result = await command_handler.handle_prefix_command(mock_client, mock_message)
            
            # Verify
            self.assertTrue(result)
            # Should NOT send NOT_AUTHORIZED
            mock_message.channel.send.assert_called()
            args, _ = mock_message.channel.send.call_args
            self.assertNotEqual(args[0], ui.FLAVOR_TEXT["NOT_AUTHORIZED"])
            self.assertIn("Debug Mode", args[0])

    async def test_seraph_override_fail_without_tag(self):
        """Test that authorization fails without the tag."""
        
        # Mock Client
        mock_client = MagicMock()
        
        # Mock Message (Webhook + NO Tag)
        mock_message = MagicMock()
        mock_message.content = "&debug"
        mock_message.webhook_id = 12345
        mock_message.author.display_name = "Sarah [Bot]"
        mock_message.channel.send = AsyncMock()
        
        mock_pk_data = ("Sarah", "sys1", "System", "S", "999999", "Desc")
        
        with patch('services.service.get_pk_message_data', new_callable=AsyncMock) as mock_get_pk, \
             patch('helpers.is_authorized', return_value=False) as mock_auth:
            
            mock_get_pk.return_value = mock_pk_data
            
            # Execute
            result = await command_handler.handle_prefix_command(mock_client, mock_message)
            
            # Verify
            self.assertTrue(result)
            # Should send NOT_AUTHORIZED
            mock_message.channel.send.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])

if __name__ == '__main__':
    unittest.main()
