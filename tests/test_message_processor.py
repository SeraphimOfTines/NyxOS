import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import re

# Ensure we can import modules from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import message_processor
import config
import services

class TestMessageProcessor(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Mocks
        self.client = MagicMock()
        self.client.user.id = 12345
        self.client.user.display_name = "NyxOS"
        self.client.user.name = "NyxOS"
        self.client.processing_locks = set()
        self.client.boot_cleared_channels = set()
        self.client.last_bot_message_id = {}
        self.client.good_bot_cooldowns = {}
        self.client.active_views = {}
        self.client.suppress_embeds_later = MagicMock()
        self.client.loop.create_task = MagicMock()

        self.message = MagicMock()
        self.message.id = 1001
        self.message.channel.id = 999
        self.message.channel.name = "general"
        self.message.author.id = 888
        self.message.author.display_name = "User"
        self.message.author.name = "User"
        self.message.content = "Hello"
        self.message.attachments = []
        self.message.webhook_id = None
        self.message.mentions = []
        self.message.role_mentions = []
        self.message.reference = None
        
        # Async Mocks for awaited methods
        self.message.channel.fetch_message = AsyncMock()
        self.message.channel.send = AsyncMock()
        self.message.reply = AsyncMock()
        self.message.add_reaction = AsyncMock()
        
        # Mock history async iterator
        async def mock_history(*args, **kwargs):
            if False: yield None # Make it a generator
            return
        self.message.channel.history.side_effect = mock_history
        
        # Async Context Managers for channel.typing()
        self.message.channel.typing.return_value.__aenter__.return_value = None
        self.message.channel.typing.return_value.__aexit__.return_value = None

        # Config patches
        self.bot_role_patch = patch('config.BOT_ROLE_IDS', [555])
        self.bot_role_patch.start()
        
        self.context_window_patch = patch('config.CONTEXT_WINDOW', 5)
        self.context_window_patch.start()

        # Mock Service Methods
        self.service_patch = patch('services.service')
        self.mock_service = self.service_patch.start()
        self.mock_service.get_system_proxy_tags = AsyncMock(return_value=[])
        self.mock_service.get_pk_user_data = AsyncMock(return_value=None)
        self.mock_service.query_lm_studio = AsyncMock(return_value="AI Response")
        self.mock_service.generate_search_queries = AsyncMock(return_value=[])
        self.mock_service.my_system_members = set()

    async def asyncTearDown(self):
        self.bot_role_patch.stop()
        self.context_window_patch.stop()
        self.service_patch.stop()

    # --- test_trigger_conditions ---
    async def test_trigger_conditions(self):
        """
        Test: Bot mentioned -> should_respond = True.
        Test: Reply to Bot -> should_respond = True.
        Test: Reply to random user -> should_respond = False.
        """
        # Mock memory_manager to allow channel
        with patch('message_processor.memory_manager.get_allowed_channels', return_value=[999]), \
             patch('message_processor.memory_manager.log_conversation'), \
             patch('message_processor.memory_manager.clear_channel_memory'):
            
            # 1. Mention Trigger
            self.message.mentions = [self.client.user]
            self.message.content = "<@12345> Hello"
            await message_processor.process_message(self.client, self.message)
            self.mock_service.query_lm_studio.assert_called()
            
            # Reset
            self.mock_service.query_lm_studio.reset_mock()
            self.message.mentions = []
            
            # 2. Reply to Bot Trigger
            ref_msg = MagicMock()
            ref_msg.author.id = self.client.user.id # Bot ID
            ref_msg.id = 500
            self.message.reference = MagicMock()
            self.message.reference.resolved = ref_msg
            self.message.content = "Reply"
            
            await message_processor.process_message(self.client, self.message)
            self.mock_service.query_lm_studio.assert_called()
            
            # Reset
            self.mock_service.query_lm_studio.reset_mock()
            
            # 3. Reply to Random User (No Trigger)
            ref_msg.author.id = 777 # Random User
            await message_processor.process_message(self.client, self.message)
            self.mock_service.query_lm_studio.assert_not_called()

    # --- test_good_bot_logic ---
    async def test_good_bot_logic(self):
        """
        Input "Good bot" -> Verify memory_manager.increment_good_bot is called.
        Verify cooldown prevents spamming.
        """
        self.message.content = "Good bot"
        # Must be a reply or ping to count (logic requirement)
        self.message.mentions = [self.client.user]

        with patch('message_processor.memory_manager.increment_good_bot') as mock_inc:
            # 1. First Call
            await message_processor.process_message(self.client, self.message)
            mock_inc.assert_called_once()
            
            # 2. Second Call (Immediate) -> Should be blocked by cooldown
            mock_inc.reset_mock()
            await message_processor.process_message(self.client, self.message)
            mock_inc.assert_not_called()

    # --- test_proxy_filtering ---
    async def test_proxy_filtering(self):
        """
        Simulate a message matching a system proxy tag -> Verify process_message returns early.
        """
        self.message.content = "Seraph: Test Proxy"
        
        # Mock get_system_proxy_tags to return a match
        tags = [{'prefix': 'Seraph:', 'suffix': None}]
        self.mock_service.get_system_proxy_tags.return_value = tags
        
        with patch('message_processor.helpers.matches_proxy_tag', return_value=True):
            # Run
            await message_processor.process_message(self.client, self.message)
            
            # Verify it returned early (didn't query LLM)
            self.mock_service.query_lm_studio.assert_not_called()

if __name__ == '__main__':
    unittest.main()