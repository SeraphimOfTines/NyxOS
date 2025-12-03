import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import message_processor
import discord
import config

# Helper class for async iteration
class AsyncIter:
    def __init__(self, items):
        self.items = list(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

class TestMessageProcessor:
    
    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.user.id = 8888
        client.user.display_name = "NyxOS"
        client.user.name = "nyxos"
        client.user.mention = "<@8888>"
        client.boot_cleared_channels = set()
        client.processing_locks = set()
        client.good_bot_cooldowns = {}
        client.last_bot_message_id = {}
        client.active_views = {}
        client.loop.create_task = MagicMock()
        return client

    @pytest.fixture
    def mock_message(self):
        msg = MagicMock()
        msg.id = 101
        msg.content = "Hello"
        msg.author.id = 123
        msg.author.name = "user"
        msg.author.display_name = "User"
        msg.author.bot = False
        msg.channel.id = 777
        msg.channel.name = "general"
        msg.mentions = []
        msg.role_mentions = []
        msg.reference = None
        msg.webhook_id = None
        msg.attachments = []
        msg.channel.typing.return_value.__aenter__ = AsyncMock()
        msg.channel.typing.return_value.__aexit__ = AsyncMock()
        msg.channel.fetch_message = AsyncMock() # Mock this
        
        # Mock history
        msg.channel.history = MagicMock(return_value=AsyncIter([]))
        
        return msg

    @pytest.mark.asyncio
    async def test_trigger_mention(self, mock_client, mock_message):
        mock_message.content = "<@8888> Hello"
        mock_message.mentions = [mock_client.user]
        
        # Mock fetch_message for Ghost Check
        mock_message.channel.fetch_message = AsyncMock(return_value=mock_message)
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None), \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)), \
             patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query, \
             patch('memory_manager.get_allowed_channels', return_value=[777]), \
             patch('memory_manager.log_conversation'):
            
            await message_processor.process_message(mock_client, mock_message)
            
            assert mock_query.called

    @pytest.mark.asyncio
    async def test_trigger_reply_to_bot(self, mock_client, mock_message):
        mock_message.content = "Hello"
        
        # Setup Reference
        ref = MagicMock()
        ref.resolved.author.id = mock_client.user.id # Reply to bot     
        mock_message.reference = ref                                    
        
        # Mock fetch_message for Ghost Check
        mock_message.channel.fetch_message = AsyncMock(return_value=mock_message)
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.get_pk_user_data', new_callable=AsyncMock, return_value=None), \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock, return_value=(None, None, None, None, None, None)), \
             patch('services.service.generate_search_queries', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query, \
             patch('memory_manager.get_allowed_channels', return_value=[777]), \
             patch('memory_manager.log_conversation'):
            
            await message_processor.process_message(mock_client, mock_message)
            
            assert mock_query.called

    @pytest.mark.asyncio
    async def test_no_trigger_random(self, mock_client, mock_message):
        mock_message.content = "Hello world"
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query:
            
            await message_processor.process_message(mock_client, mock_message)
            
            assert not mock_query.called

    @pytest.mark.asyncio
    async def test_good_bot_logic(self, mock_client, mock_message):
        mock_message.content = "Good bot"
        mock_message.mentions = [mock_client.user] # Ping to trigger check
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]), \
             patch('memory_manager.increment_good_bot') as mock_inc, \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock) as mock_pk:
            
            # Mock PK return (Not a webhook)
            mock_pk.return_value = (None, None, None, None, None, None)

            await message_processor.process_message(mock_client, mock_message)
            
            assert mock_inc.called
            mock_message.add_reaction.assert_called()

    @pytest.mark.asyncio
    async def test_good_bot_cooldown(self, mock_client, mock_message):
        mock_message.content = "Good bot"
        mock_message.mentions = [mock_client.user]
        
        # Set cooldown
        import time
        mock_client.good_bot_cooldowns[mock_message.author.id] = time.time() 
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=[]), \
             patch('memory_manager.increment_good_bot') as mock_inc, \
             patch('services.service.get_pk_message_data', new_callable=AsyncMock) as mock_pk:
             
             mock_pk.return_value = (None, None, None, None, None, None)
             
             await message_processor.process_message(mock_client, mock_message)
             
             assert not mock_inc.called

    @pytest.mark.asyncio
    async def test_proxy_filtering(self, mock_client, mock_message):
        # Message matches a proxy tag
        mock_message.content = "Seraph: Hello"
        
        tags = [{'prefix': 'Seraph:', 'suffix': ''}]
        
        with patch('asyncio.sleep'), \
             patch('services.service.get_system_proxy_tags', new_callable=AsyncMock, return_value=tags), \
             patch('services.service.query_lm_studio', new_callable=AsyncMock) as mock_query:
            
            await message_processor.process_message(mock_client, mock_message)
            
            # Should return early, so no query
            assert not mock_query.called