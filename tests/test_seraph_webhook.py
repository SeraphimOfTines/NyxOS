import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS
import config

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_utils import AsyncIter

class TestSeraphWebhook(unittest.IsolatedAsyncioTestCase):
    
    async def test_seraph_webhook_override(self):
        # Mock Client
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.user.display_name = "NyxOS"
        mock_client.processing_locks = set()
        mock_client.abort_signals = set()
        mock_client.active_views = {}
        mock_client.active_bars = {}
        mock_client.boot_cleared_channels = set()
        mock_client.channel_cutoff_times = {}
        mock_client.good_bot_cooldowns = {}
        mock_client.last_bot_message_id = {}
        mock_client.loop.create_task = MagicMock()
        mock_client.schedule_next_heartbeat = MagicMock()
        
        # Volition
        mock_client.volition = MagicMock()
        mock_client.volition.update_buffer = AsyncMock()
        
        # Emotional Core (Sync)
        mock_client.emotional_core = MagicMock()
        mock_client.emotional_core.process_interaction = MagicMock()

        # Mock Message (Webhook with Seraphim Tag)
        message = AsyncMock()
        message.content = "Hello Bot"
        message.author.id = 99999 # Webhook ID
        message.author.display_name = "Sarah [⛩ Seraphim ⛩]" # TARGET STRING
        message.webhook_id = 99999
        message.channel.id = 777
        message.channel.name = "general"
        message.mentions = [mock_client.user] # Ping to trigger response
        message.role_mentions = []
        message.attachments = []
        message.reference = None
        
        # Mock typing
        message.channel.typing = MagicMock()
        message.channel.typing.return_value.__aenter__ = AsyncMock()
        message.channel.typing.return_value.__aexit__ = AsyncMock()
        
        # Setup History Mock
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        # Config System ID
        config.MY_SYSTEM_ID = "seraph-system-id"
        
        # Patches
        with patch('NyxOS.client', mock_client):
             # Mock PK to fail/return nothing
             with patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)):
                 # Mock Auth to fail (ensure we rely on System ID override)
                 with patch('helpers.is_authorized', return_value=False):
                     # Mock other services
                     with patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]):
                         with patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None):
                             with patch('memory_manager.get_allowed_channels', return_value=[777]):
                                 with patch('memory_manager.get_server_setting', return_value=False): # Global chat off
                                     with patch('memory_manager.log_conversation'):
                                         # Mock Downstream
                                         with patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query:
                                             
                                             # Execute
                                             await NyxOS.on_message(message)
                                             
                                             # Verify
                                             # If access was granted, query_lm_studio should be called
                                             mock_query.assert_called()
                                             
    async def test_seraph_webhook_fail_without_tag(self):
        # Verify that without the tag, access is DENIED (since we mock auth=False and PK=None)
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.processing_locks = set()
        mock_client.abort_signals = set()
        mock_client.active_views = {}
        mock_client.active_bars = {}
        mock_client.boot_cleared_channels = set()
        mock_client.channel_cutoff_times = {}
        mock_client.good_bot_cooldowns = {}
        mock_client.last_bot_message_id = {}
        mock_client.loop.create_task = MagicMock()
        mock_client.schedule_next_heartbeat = MagicMock()
        
        mock_client.volition = MagicMock()
        mock_client.volition.update_buffer = AsyncMock()
        
        # Emotional Core (Sync)
        mock_client.emotional_core = MagicMock()
        mock_client.emotional_core.process_interaction = MagicMock()

        message = AsyncMock()
        message.content = "Hello Bot"
        message.author.id = 99999
        message.author.display_name = "Sarah [Random System]" # NO TAG
        message.webhook_id = 99999
        message.channel.id = 777
        message.mentions = [mock_client.user]
        message.role_mentions = []
        message.attachments = []
        message.reference = None
        
        message.channel.typing = MagicMock()
        message.channel.typing.return_value.__aenter__ = AsyncMock()
        message.channel.typing.return_value.__aexit__ = AsyncMock()
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        config.MY_SYSTEM_ID = "seraph-system-id"
        
        with patch('NyxOS.client', mock_client):
             with patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)):
                 with patch('helpers.is_authorized', return_value=False):
                     with patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]):
                         with patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None):
                             with patch('memory_manager.get_allowed_channels', return_value=[777]):
                                 with patch('memory_manager.get_server_setting', return_value=False):
                                     with patch('memory_manager.log_conversation'):
                                         with patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query:
                                             
                                             await NyxOS.on_message(message)
                                             
                                             # Verify - Should NOT be called
                                             mock_query.assert_not_called()
