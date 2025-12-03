import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import config

class TestGlobalAuthBypass(unittest.IsolatedAsyncioTestCase):
    
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
        config.MY_SYSTEM_ID = "sys_123"

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
        # Not admin
        author.roles = [] 
        
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
        msg.guild.get_member.return_value = author
        msg.guild.fetch_member = AsyncMock(return_value=author)
        
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
    @patch('memory_manager.get_allowed_channels', return_value=[100]) # Whitelist only includes 100
    @patch('memory_manager.get_server_setting', return_value=True) # GLOBAL CHAT ON
    @patch('helpers.clean_name_logic', return_value="TestUser")
    @patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None))
    @patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None)
    @patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[])
    @patch('services.service.query_lm_studio', new_callable=AsyncMock, return_value="Response")
    @patch('helpers.is_authorized', return_value=False) # USER IS NOT AUTH
    async def test_global_mode_bypasses_auth_and_whitelist(self, mock_is_auth, mock_query, *args):
        """
        Test that when Global Mode is ON:
        1. Non-whitelisted channel (200) is allowed.
        2. Non-authorized user (Auth=False) is allowed.
        """
        
        # Message in NON-whitelisted channel (200)
        # Mentioning bot so 'should_respond' is True
        msg = self.create_mock_message("<@12345> hello", 888, 200)
        msg.mentions = [self.mock_client.user]
        
        # Mock fetch_message for Ghost Check
        msg.channel.fetch_message = AsyncMock(return_value=msg)
        
        await NyxOS.on_message(msg)
        
        # Should have queried LLM
        mock_query.assert_called()
        
    @patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[])
    @patch('memory_manager.log_conversation')
    @patch('memory_manager.clear_channel_memory')
    @patch('memory_manager.get_allowed_channels', return_value=[100])
    @patch('memory_manager.get_server_setting', return_value=False) # GLOBAL CHAT OFF
    @patch('helpers.clean_name_logic', return_value="TestUser")
    @patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None))
    @patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None)
    @patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[])
    @patch('services.service.query_lm_studio', new_callable=AsyncMock, return_value="Response")
    @patch('helpers.is_authorized', return_value=False) # USER IS NOT AUTH
    async def test_normal_mode_blocks_unauth_user(self, mock_is_auth, mock_query, *args):
        """
        Test that when Global Mode is OFF:
        1. Non-authorized user is BLOCKED even if channel is valid (or bypassed by ping).
        Wait, logic is: if not is_own and not is_authorized -> Return.
        So normal mode DOES require auth for everyone?
        Yes, README says "Only Admins and Special roles".
        """
        
        # Message in whitelisted channel (100) just to isolate Auth check
        msg = self.create_mock_message("<@12345> hello", 888, 100)
        msg.mentions = [self.mock_client.user]
        
        # Mock fetch_message for Ghost Check
        msg.channel.fetch_message = AsyncMock(return_value=msg)
        
        await NyxOS.on_message(msg)
        
        # Should NOT query LLM
        mock_query.assert_not_called()

if __name__ == '__main__':
    unittest.main()