import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import services

class TestPKRedundancy(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        # Reset config
        self.original_use_local = config.USE_LOCAL_PLURALKIT
        self.original_msg_api = config.PLURALKIT_MESSAGE_API
        self.original_user_api = config.PLURALKIT_USER_API
        
        # Enable Local PK for testing redundancy
        config.USE_LOCAL_PLURALKIT = True
        config.PLURALKIT_MESSAGE_API = "http://local-pk:5000/messages/{}"
        config.PLURALKIT_USER_API = "http://local-pk:5000/users/{}"
        
        self.service = services.APIService()
        # Mock http_session
        self.service.http_session = MagicMock()
        
    async def asyncTearDown(self):
        config.USE_LOCAL_PLURALKIT = self.original_use_local
        config.PLURALKIT_MESSAGE_API = self.original_msg_api
        config.PLURALKIT_USER_API = self.original_user_api
        await self.service.close()

    async def test_get_pk_user_data_fallback(self):
        """Test that get_pk_user_data falls back to official API on local failure."""
        user_id = 12345
        local_url = config.PLURALKIT_USER_API.format(user_id)
        official_url = f"https://api.pluralkit.me/v2/users/{user_id}"
        
        # Mocks
        # 1. Local Response (Fail)
        resp_local = AsyncMock()
        resp_local.status = 404
        
        ctx_local = AsyncMock()
        ctx_local.__aenter__.return_value = resp_local
        ctx_local.__aexit__.return_value = None
        
        # 2. Official Response (Success)
        resp_official = AsyncMock()
        resp_official.status = 200
        resp_official.json = AsyncMock(return_value={"id": "sys1", "tag": "Tag"})
        
        ctx_official = AsyncMock()
        ctx_official.__aenter__.return_value = resp_official
        ctx_official.__aexit__.return_value = None
        
        def side_effect(url, *args, **kwargs):
            if url == local_url:
                return ctx_local
            elif url == official_url:
                return ctx_official
            return AsyncMock()
            
        self.service.http_session.get.side_effect = side_effect
        
        # Execute
        result = await self.service.get_pk_user_data(user_id)
        
        # Verify
        self.assertIsNotNone(result)
        self.assertEqual(result['system_id'], "sys1")
        
        # Check calls
        calls = self.service.http_session.get.call_args_list
        urls_called = [c[0][0] for c in calls]
        self.assertIn(local_url, urls_called)
        self.assertIn(official_url, urls_called)

    async def test_get_pk_message_data_fallback(self):
        """Test that get_pk_message_data falls back to official API on local failure."""
        msg_id = 999
        local_url = config.PLURALKIT_MESSAGE_API.format(msg_id)
        official_url = f"https://api.pluralkit.me/v2/messages/{msg_id}"
        
        # 1. Local Response (Error)
        resp_local = AsyncMock()
        resp_local.status = 500
        resp_local.json = AsyncMock(return_value={}) # Ensure json is awaitable even if not called
        
        ctx_local = AsyncMock()
        ctx_local.__aenter__.return_value = resp_local
        ctx_local.__aexit__.return_value = None
        
        # 2. Official Response (Success)
        resp_official = AsyncMock()
        resp_official.status = 200
        resp_official.json = AsyncMock(return_value={
            "member": {"name": "Member", "display_name": "Display"},
            "system": {"id": "sys1", "name": "System", "tag": "Tag"},
            "sender": 555
        })
        
        ctx_official = AsyncMock()
        ctx_official.__aenter__.return_value = resp_official
        ctx_official.__aexit__.return_value = None
        
        def side_effect(url, *args, **kwargs):
            if url == local_url:
                return ctx_local
            elif url == official_url:
                return ctx_official
            print(f"Unexpected URL: {url}")
            return AsyncMock()
            
        self.service.http_session.get.side_effect = side_effect
        
        # Execute
        result = await self.service.get_pk_message_data(msg_id)
        
        # Verify
        self.assertIsNotNone(result[0], "Result should not be None tuple")
        self.assertEqual(result[0], "Display")
        self.assertEqual(result[4], 555)
        
        # Check calls
        calls = self.service.http_session.get.call_args_list
        urls_called = [c[0][0] for c in calls]
        # It tries local 3 times (retry loop) then official
        self.assertIn(local_url, urls_called)
        self.assertIn(official_url, urls_called)

if __name__ == '__main__':
    unittest.main()