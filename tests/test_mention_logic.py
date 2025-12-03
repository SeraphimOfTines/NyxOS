import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import config

class TestMentionLogic(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Patch the global client in NyxOS module
        self.client_patcher = patch('NyxOS.client')
        self.mock_client = self.client_patcher.start()
        
        # Setup Mock Client Attributes
        self.mock_client.user = MagicMock()
        self.mock_client.user.id = 12345
        self.mock_client.user.display_name = "NyxOS"
        self.mock_client.user.name = "nyxos"
        self.mock_client.processing_locks = set()
        self.mock_client.boot_cleared_channels = set()
        self.mock_client.last_bot_message_id = {}
        self.mock_client.good_bot_cooldowns = {}
        self.mock_client.active_views = {}
        self.mock_client.channel_cutoff_times = {}
        
        # Mock config roles
        config.BOT_ROLE_IDS = [555]
        config.ADMIN_ROLE_IDS = [999]

    def tearDown(self):
        self.client_patcher.stop()
        
    # Helper to create an async iterator for history
    class AsyncIterator:
        def __init__(self, seq):
            self.iter = iter(seq)
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self.iter)
            except StopIteration:
                raise StopAsyncIteration

    def create_mock_message(self, content, author_id, channel_id):
        author = MagicMock()
        author.id = author_id
        author.bot = False
        author.name = "TestUser"
        author.display_name = "TestUser"
        author.mention = f"<@{author_id}>"
        
        msg = MagicMock()
        msg.id = 1
        msg.author = author
        msg.channel.id = channel_id 
        msg.channel.name = "random-channel"
        msg.content = content
        msg.clean_content = content
        msg.mentions = []
        msg.role_mentions = []
        msg.webhook_id = None
        msg.attachments = []
        msg.reference = None
        msg.guild = MagicMock()
        
        # Mock typing context manager
        msg.channel.typing = MagicMock()
        msg.channel.typing.return_value.__aenter__ = AsyncMock()
        msg.channel.typing.return_value.__aexit__ = AsyncMock()
        
        # Mock history as empty
        msg.channel.history = MagicMock(return_value=self.AsyncIterator([]))
        
        return msg

    @patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[])
    @patch('memory_manager.log_conversation')
    @patch('memory_manager.clear_channel_memory')
    @patch('memory_manager.get_allowed_channels', return_value=[100]) # Channel 100 is whitelisted
    @patch('memory_manager.get_server_setting', return_value=False) # Global Chat OFF
    async def test_mention_bypasses_whitelist(self, mock_setting, mock_allowed, mock_clear, mock_log, mock_tags):
        """Test that tagging the bot (User Mention) bypasses channel whitelist."""
        
        msg = self.create_mock_message("<@12345> hello", 888, 200)
        msg.mentions = [self.mock_client.user] # Tagged bot
        
        # Mock fetch_message for Ghost Check
        msg.channel.fetch_message = AsyncMock(return_value=msg)
        
        # Mock services
        with patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None), \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)), \
             patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock, return_value="Response") as mock_query, \
             patch('helpers.is_authorized', return_value=True): # Auth pass
             
             # Run on_message
             await NyxOS.on_message(msg)
             
             # Verify query_lm_studio called
             mock_query.assert_called()

    @patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[])
    @patch('memory_manager.log_conversation')
    @patch('memory_manager.clear_channel_memory')
    @patch('memory_manager.get_allowed_channels', return_value=[100])
    @patch('memory_manager.get_server_setting', return_value=False)
    @patch('helpers.clean_name_logic', return_value="TestUser") # Mock to avoid regex on MagicMock
    async def test_role_mention_bypasses_whitelist(self, mock_clean, mock_setting, mock_allowed, mock_clear, mock_log, mock_tags):
        """Test that tagging the bot (Wake Role) bypasses channel whitelist."""
        
        msg = self.create_mock_message("<@&555> hello", 888, 200)
        
        # Tagged Wake Role (555)
        role_mock = MagicMock()
        role_mock.id = 555
        msg.role_mentions = [role_mock]
        
        # Mock fetch_message for Ghost Check
        msg.channel.fetch_message = AsyncMock(return_value=msg)
        
        # Mock services
        with patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None), \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)), \
             patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock, return_value="Response") as mock_query, \
             patch('helpers.is_authorized', return_value=True): 
             
             await NyxOS.on_message(msg)
             
             mock_query.assert_called()

    @patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[])
    @patch('memory_manager.log_conversation')
    @patch('memory_manager.clear_channel_memory')
    @patch('memory_manager.get_allowed_channels', return_value=[100])
    @patch('memory_manager.get_server_setting', return_value=False)
    async def test_no_mention_respects_whitelist(self, mock_setting, mock_allowed, mock_clear, mock_log, mock_tags):
        """Test that normal messages in non-whitelisted channels are IGNORED."""
        
        msg = self.create_mock_message("hello there", 888, 200)
        
        # Mock services
        with patch('services.service.get_pk_user_data', return_value=None), \
             patch('services.service.get_pk_message_data', return_value=(None, None, None, None, None, None)), \
             patch('services.service.query_lm_studio') as mock_query:
             
             await NyxOS.on_message(msg)
             
             mock_query.assert_not_called()



if __name__ == '__main__':
    unittest.main()