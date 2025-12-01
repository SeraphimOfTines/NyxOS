import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
from collections import OrderedDict

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import services
import helpers
import command_handler

class TestPKAdminAuth(unittest.IsolatedAsyncioTestCase):

    @patch.object(config, 'ADMIN_USER_IDS', [123456789])
    def test_is_authorized_with_user_id(self):
        """Test that a user ID in ADMIN_USER_IDS is authorized."""
        # Test int
        self.assertTrue(helpers.is_authorized(123456789))
        # Test string
        self.assertTrue(helpers.is_authorized("123456789"))
        # Test User Object
        user = MagicMock()
        user.id = 123456789
        self.assertTrue(helpers.is_authorized(user))
        
        # Negative test
        self.assertFalse(helpers.is_authorized(999999))

    @patch.object(services.service, 'pk_message_cache', new_callable=OrderedDict)
    async def test_pk_message_caching(self, mock_cache):
        """Test that get_pk_message_data uses cache."""
        # Ensure cache is empty
        services.service.pk_message_cache.clear()
        
        # Mock API/DB return
        # (Name, SysID, SysName, SysTag, SenderID, Desc)
        expected_result = ("Name", "SysID", "SysName", "SysTag", 123456789, "Desc")
        
        # Mock the http session to avoid real calls
        services.service.http_session = MagicMock()
        services.service.http_session.get.return_value.__aenter__.return_value.status = 200
        services.service.http_session.get.return_value.__aenter__.return_value.json = AsyncMock(return_value={
            "member": {"name": "Name", "display_name": "Name", "description": "Desc"},
            "system": {"id": "SysID", "name": "SysName", "tag": "SysTag"},
            "sender": 123456789
        })
        
        # 1. First Call (Miss) - Should hit API
        res1 = await services.service.get_pk_message_data(1001)
        self.assertEqual(res1[4], 123456789)
        self.assertIn(1001, services.service.pk_message_cache)
        
        # 2. Second Call (Hit) - Should NOT hit API
        services.service.http_session.get.reset_mock() # Reset calls
        
        res2 = await services.service.get_pk_message_data(1001)
        self.assertEqual(res2[4], 123456789)
        services.service.http_session.get.assert_not_called()

    @patch.object(config, 'ADMIN_USER_IDS', [888888])
    @patch('services.service.get_pk_message_data', new_callable=AsyncMock)
    async def test_proxy_command_auth(self, mock_get_pk):
        """Test that a proxy message from an admin is authorized in command handler."""
        
        # Mock PK Service to return Admin ID (888888) as sender
        mock_get_pk.return_value = ("Proxy", "SysID", "SysName", "Tag", 888888, "Desc")
        
        # Mock Message
        message = AsyncMock()
        message.content = "&reboot"
        message.webhook_id = 99999 # It is a webhook
        message.id = 55555
        message.author.id = 99999 # Webhook ID (NOT Admin)
        message.channel.id = 123123 # Needs to be int for json
        message.channel.send = AsyncMock()
        
        # Mock Client
        client = MagicMock()
        client.close = AsyncMock() # Must be awaitable

        # Mock helpers.is_authorized to verify it receives the resolved ID
        with patch('helpers.is_authorized') as mock_auth:
            mock_auth.return_value = True
            
            # Run Handler
            # We patch open/json/os to prevent actual file writes during test
            with patch('builtins.open', new_callable=MagicMock), \
                 patch('json.dump'), \
                 patch('os.fsync'), \
                 patch('sys.argv', ['script']), \
                 patch('os.execl'):
                 
                await command_handler.handle_prefix_command(client, message)
            
            # Verify is_authorized was called with the RESOLVED ID (888888), not Webhook ID
            mock_auth.assert_called_with(888888)
            
            # Verify PK lookup happened
            mock_get_pk.assert_called_with(55555)

if __name__ == '__main__':
    unittest.main()
