import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import json

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import services
import config

class TestAPIService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.service = services.APIService()
        # Create a MagicMock for the session, not AsyncMock, because we access .get/.post attributes
        self.service.http_session = MagicMock() 

    async def asyncTearDown(self):
        await self.service.close()

    def _mock_response(self, status=200, json_data=None, text_data=""):
        """Helper to create a mock response context manager."""
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.json.return_value = json_data
        mock_resp.text.return_value = text_data
        
        # The mock context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    # --- test_pluralkit_caching ---
    async def test_pluralkit_caching(self):
        """
        Mock get_pk_user_data. Call twice. Ensure second call hits cache (no HTTP request).
        """
        user_id = "12345"
        expected_url = config.PLURALKIT_USER_API.format(user_id)
        mock_resp_data = {"id": "abcde", "tag": "TEST"}
        
        # Configure Mock
        # .get() returns the context manager
        self.service.http_session.get.return_value = self._mock_response(json_data=mock_resp_data)

        # 1. First Call (Should hit API)
        result1 = await self.service.get_pk_user_data(user_id)
        self.assertEqual(result1['system_id'], "abcde")
        self.service.http_session.get.assert_called_once_with(expected_url)
        
        # 2. Second Call (Should hit Cache)
        self.service.http_session.get.reset_mock() # Reset call count
        result2 = await self.service.get_pk_user_data(user_id)
        self.assertEqual(result2['system_id'], "abcde")
        self.service.http_session.get.assert_not_called()

    # --- test_generate_search_queries ---
    async def test_generate_search_queries(self):
        """
        Mock LLM response.
        Test filtering: Ensure &web and markdown bullets are stripped.
        Test "NO_SEARCH" response handling.
        """
        # Mock Config Kagi Token
        with patch('config.KAGI_API_TOKEN', "fake_token"):
            
            # Case 1: Normal Search Query Generation
            mock_llm_response = {
                "choices": [{
                    "message": {
                        "content": "1. python tutorial\n- &web advanced python"
                    }
                }]
            }
            self.service.http_session.post.return_value = self._mock_response(json_data=mock_llm_response)
            
            queries = await self.service.generate_search_queries("Learn Python", [], force_search=False)
            
            # Check filtering
            self.assertIn("python tutorial", queries)
            self.assertIn("advanced python", queries) # &web and dash stripped
            self.assertNotIn("&web", queries[1])
            
            # Case 2: NO_SEARCH
            mock_llm_response["choices"][0]["message"]["content"] = "NO_SEARCH"
            self.service.http_session.post.return_value = self._mock_response(json_data=mock_llm_response)
            
            queries = await self.service.generate_search_queries("Hello", [], force_search=False)
            self.assertEqual(queries, [])

            # Case 3: Force Search Fallback (Empty result from cleaning)
            mock_llm_response["choices"][0]["message"]["content"] = "" # Empty
            self.service.http_session.post.return_value = self._mock_response(json_data=mock_llm_response)
            
            queries = await self.service.generate_search_queries("Search This", [], force_search=True)
            self.assertEqual(queries, ["Search This"])

    # --- test_query_lm_studio_payload ---
    async def test_query_lm_studio_payload(self):
        """
        Verify system_prompt is constructed correctly.
        Verify history_messages are included.
        Verify "Coalescing" logic.
        Verify _strip_images fallback logic.
        """
        # Setup Mocks
        channel = MagicMock()
        channel.id = "c1"
        channel.name = "general"
        
        mock_response_content = "AI Response"
        self.service.http_session.post.return_value = self._mock_response(
            json_data={"choices": [{"message": {"content": mock_response_content}}]}
        )
        
        # Mock memory_manager to avoid DB calls
        with patch('services.memory_manager.write_context_buffer', new=AsyncMock()):
            
            # 1. Verify Payload Construction & Coalescing
            history = [
                {"role": "user", "content": "Msg 1"},
                {"role": "user", "content": "Msg 2"} 
            ]
            
            await self.service.query_lm_studio("Msg 3", "User", "", history, channel)
            
            # Inspect the call to http_session.post
            call_args = self.service.http_session.post.call_args
            _, kwargs = call_args
            payload = kwargs['json']
            messages = payload['messages']
            
            # Check System Prompt
            self.assertEqual(messages[0]['role'], 'system')
            
            # Check Coalescing
            user_msgs = [m for m in messages if m['role'] == 'user']
            self.assertEqual(len(user_msgs), 1) # Coalesced
            
            content_list = user_msgs[0]['content']
            texts = [item['text'] for item in content_list if item['type'] == 'text']
            combined_text = "".join(texts)
            
            self.assertIn("Msg 1", combined_text)
            self.assertIn("Msg 2", combined_text)
            self.assertIn("Msg 3", combined_text)

            # 2. Verify Image Strip Fallback
            self.service.http_session.post.reset_mock() # Reset call count from previous test step
            
            # Create side_effect: First call returns 400, Second returns 200
            mock_ctx_400 = self._mock_response(status=400, text_data="Bad Request")
            mock_ctx_200 = self._mock_response(status=200, 
                json_data={"choices": [{"message": {"content": "Success"}}]})
            
            self.service.http_session.post.side_effect = [mock_ctx_400, mock_ctx_200]
            
            # Input with image
            await self.service.query_lm_studio("Look", "User", "", [], channel, image_data_uri="data:image/png...")
            
            # Should have called post twice
            self.assertEqual(self.service.http_session.post.call_count, 2)
            
            # Second call should NOT have image_url
            second_call_payload = self.service.http_session.post.call_args_list[1][1]['json']
            last_msg = second_call_payload['messages'][-1]
            content_str = last_msg['content']
            
            self.assertIsInstance(content_str, str)
            self.assertIn("(Image Download Failed)", content_str)
if __name__ == '__main__':
    unittest.main()