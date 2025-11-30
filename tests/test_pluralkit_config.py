import unittest
import os
import sys
import importlib
from unittest.mock import patch, MagicMock
import asyncio

# We need to add the parent directory to sys.path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestPluralKitConfig(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Back up the original environment
        self.original_env = os.environ.copy()
        # Ensure we start with a clean slate for config
        if 'config' in sys.modules:
            del sys.modules['config']

    def tearDown(self):
        # Restore environment
        os.environ = self.original_env
        # Restore config to original state (best effort)
        if 'config' in sys.modules:
            importlib.reload(sys.modules['config'])

    def test_config_defaults_to_public_api(self):
        """Test that without env vars, it defaults to Public API."""
        # Ensure environment is clean of our toggle
        if "USE_LOCAL_PLURALKIT" in os.environ:
            del os.environ["USE_LOCAL_PLURALKIT"]
        
        # IGNORE config.txt by simulating it doesn't exist
        with patch('builtins.open', side_effect=FileNotFoundError):
            import config
            importlib.reload(config)
        
        self.assertFalse(config.USE_LOCAL_PLURALKIT)
        self.assertIn("api.pluralkit.me", config.PLURALKIT_MESSAGE_API)
        self.assertIn("api.pluralkit.me", config.PLURALKIT_USER_API)

    def test_config_switches_to_local_api(self):
        """Test that setting env var switches to Local API."""
        os.environ["USE_LOCAL_PLURALKIT"] = "True"
        os.environ["LOCAL_PLURALKIT_API_URL"] = "http://custom-local:9999/v2"
        
        import config
        importlib.reload(config)
        
        self.assertTrue(config.USE_LOCAL_PLURALKIT)
        self.assertIn("custom-local:9999", config.PLURALKIT_MESSAGE_API)
        self.assertIn("custom-local:9999", config.PLURALKIT_USER_API)

    def test_config_handles_bad_boolean_input(self):
        """Test that invalid boolean strings default to False (Public API)."""
        # "False" inputs
        for bad_input in ["False", "0", "no", "garbage"]:
            os.environ["USE_LOCAL_PLURALKIT"] = bad_input
            import config
            importlib.reload(config)
            self.assertFalse(config.USE_LOCAL_PLURALKIT, f"Failed on input: {bad_input}")
            self.assertIn("api.pluralkit.me", config.PLURALKIT_MESSAGE_API)

        # "True" inputs
        for good_input in ["True", "1", "t", "true"]:
            os.environ["USE_LOCAL_PLURALKIT"] = good_input
            import config
            importlib.reload(config)
            self.assertTrue(config.USE_LOCAL_PLURALKIT, f"Failed on input: {good_input}")

    @patch('aiohttp.ClientSession.get')
    async def test_service_uses_configured_url(self, mock_get):
        """
        Async test to verify APIService uses the URL from config.
        We reload config to Local, then check if service calls the local URL.
        """
        # 1. Set to Local
        os.environ["USE_LOCAL_PLURALKIT"] = "True"
        os.environ["LOCAL_PLURALKIT_API_URL"] = "http://localhost:5000/v2"
        
        import config
        importlib.reload(config)
        import services
        importlib.reload(services) # Reload services to ensure it sees new config
        
        # Mock response
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json.return_value = asyncio.Future()
        mock_resp.json.return_value.set_result({'id': 'test_sys', 'tag': 'test'})
        mock_get.return_value.__aenter__.return_value = mock_resp

        service = services.APIService()
        service.http_session = MagicMock()
        service.http_session.get = mock_get

        # Act
        await service.get_pk_user_data("12345")

        # Assert
        # Check that the URL passed to get() contains our local host
        # call_args returns (args, kwargs)
        args, _ = mock_get.call_args
        called_url = args[0]
        self.assertIn("localhost:5000", called_url)
        self.assertNotIn("api.pluralkit.me", called_url)

    def test_failure_simulation(self):
        """
        Simulate a 'bad configuration' scenario where the user WANTS local but config fails 
        (e.g. if logic was broken). 
        This test confirms that IF we set it to True, it IS True.
        """
        os.environ["USE_LOCAL_PLURALKIT"] = "True"
        import config
        importlib.reload(config)
        
        # Intentionally asserting the POSITIVE case to ensure logic works.
        if not config.USE_LOCAL_PLURALKIT:
             self.fail("Config failed to switch to Local mode despite env var being set.")

if __name__ == '__main__':
    unittest.main()
