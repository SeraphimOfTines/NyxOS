import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS
import config

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_utils import AsyncIter

class TestProxyReaction(unittest.IsolatedAsyncioTestCase):
    
    async def test_proxy_trigger_no_reaction(self):
        """Verify the 'trigger' message (Cly: Hi) is ignored and NOT reacted to."""
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.processing_locks = set()
        mock_client.volition = MagicMock()
        mock_client.volition.update_buffer = AsyncMock()
        mock_client.abort_signals = set()
        
        message = AsyncMock()
        message.content = "Cly: Hi!"
        message.webhook_id = None # Is human
        message.author.id = 123
        message.channel.id = 999
        message.mentions = []
        message.role_mentions = []
        
        # Patch dependencies
        # matches_proxy_tag should return True
        with patch('NyxOS.client', mock_client):
            with patch('services.service.get_all_proxy_tags', return_value=[{'prefix': 'Cly:', 'suffix': None}]):
                with patch('helpers.matches_proxy_tag', return_value=True):
                    
                    await NyxOS.on_message(message)
                    
                    # Should verify:
                    # 1. matches_proxy_tag was called
                    # 2. add_reaction was NOT called
                    
                    message.add_reaction.assert_not_called()

    async def test_webhook_pk_reaction(self):
        """Verify a valid PK webhook message GETS a reaction."""
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.processing_locks = set()
        mock_client.active_bars = {} # Not persisting
        mock_client.boot_cleared_channels = set()
        mock_client.volition = MagicMock()
        mock_client.volition.update_buffer = AsyncMock()
        mock_client.abort_signals = set()
        
        message = AsyncMock()
        message.content = "Hi!"
        message.webhook_id = 99999 # Is Webhook
        message.author.id = 99999
        message.id = 1000
        message.channel.id = 999
        message.mentions = []
        message.role_mentions = []
        
        # Patch dependencies
        # get_pk_message_data should return valid data
        pk_data = ("Name", "sysid", "SysName", "SysTag", 123, "Desc")
        
        with patch('NyxOS.client', mock_client):
            with patch('services.service.get_all_proxy_tags', return_value=[]):
                with patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=pk_data):
                     # Prevent further processing to isolate check (mock should_respond flow or let it fail gently)
                     # If we don't mock should_respond logic, it might error or do more.
                     # But since message is webhook and no pings, should_respond defaults to False.
                     # So it should just run the check and exit.
                     
                     await NyxOS.on_message(message)
                     
                     message.add_reaction.assert_called_with(config.EYE_REACTION)

    async def test_webhook_non_pk_no_reaction(self):
        """Verify a non-PK webhook message does NOT get a reaction."""
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.processing_locks = set()
        mock_client.volition = MagicMock()
        mock_client.volition.update_buffer = AsyncMock()
        mock_client.abort_signals = set()
        
        message = AsyncMock()
        message.content = "GitHub Notification"
        message.webhook_id = 88888 # Is Webhook
        message.author.id = 88888
        message.id = 2000
        message.channel.id = 999
        message.mentions = []
        
        # get_pk_message_data returns None
        pk_data = (None, None, None, None, None, None)
        
        with patch('NyxOS.client', mock_client):
            with patch('services.service.get_all_proxy_tags', return_value=[]):
                with patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=pk_data):
                     
                     await NyxOS.on_message(message)
                     
                     message.add_reaction.assert_not_called()
