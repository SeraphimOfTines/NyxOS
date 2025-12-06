import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS
import ui
import memory_manager

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_utils import AsyncIter

class TestGoodBot(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.test_dir = "tests/temp_goodbot"
        os.makedirs(self.test_dir, exist_ok=True)
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_good_bot_trigger(self):
        # Mock Client
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.user.display_name = "NyxOS"
        mock_client.last_bot_message_id = {999: 1000} # Simulate bot spoke last
        mock_client.good_bot_cooldowns = {}
        mock_client.active_views = {}
        mock_client.processing_locks = set()
        mock_client.abort_signals = set()
        mock_client._update_lru_cache = MagicMock()
        # schedule_next_heartbeat is sync
        mock_client.schedule_next_heartbeat = MagicMock()

        # Mock Message
        message = AsyncMock()
        message.content = "Good Bot!"
        message.author.id = 123
        message.author.display_name = "TestUser"
        message.author.name = "testuser"
        message.channel.id = 999
        message.mentions = [mock_client.user] # PING to trigger logic
        message.role_mentions = []
        message.webhook_id = None
        
        # get_member is sync
        mock_member = MagicMock()
        mock_member.name = "testuser"
        message.guild.get_member = MagicMock(return_value=mock_member)
        
        # Setup History Mock
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        # We need to patch the global client in NyxOS
        with patch('NyxOS.client', mock_client):
             with patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None): # No PK
                 with patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]):
                     with patch('memory_manager.increment_good_bot', return_value=5) as mock_inc:
                         
                         # Run on_message
                         await NyxOS.on_message(message)
                         
                         # Verify
                         mock_inc.assert_called_with(123, "TestUser (@testuser)")
                         message.add_reaction.assert_called_with(ui.FLAVOR_TEXT["GOOD_BOT_REACTION"])

    async def test_good_bot_cooldown(self):
        # Mock Message
        message = AsyncMock()
        message.content = "Good Bot!"
        message.author.id = 123
        message.channel.id = 999
        message.mentions = []
        message.webhook_id = None
        
        # Setup History Mock
        message.channel.history = MagicMock(return_value=AsyncIter([]))
        
        mock_client = AsyncMock()
        mock_client.user.id = 888
        mock_client.last_bot_message_id = {999: 1000}
        mock_client.processing_locks = set()
        mock_client.abort_signals = set()
        mock_client._update_lru_cache = MagicMock()
        
        # Set cooldown
        import time
        mock_client.good_bot_cooldowns = {123: time.time()} # Just happened
        
        with patch('NyxOS.client', mock_client):
             with patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]):
                 with patch('memory_manager.increment_good_bot') as mock_inc:
                     
                     await NyxOS.on_message(message)
                     
                     mock_inc.assert_not_called()
                     message.add_reaction.assert_not_called()