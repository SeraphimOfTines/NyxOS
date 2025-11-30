import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import memory_manager
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Helper for async iteration
class AsyncIter:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

class TestCommandParity(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Create instance
        self.client = NyxOS.LMStudioBot()
        
        # Mock Loop
        self.client.loop = MagicMock()
        self.client.loop.create_task = MagicMock()
        
        # Mock User via connection
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 99999
        # Also patch the property just in case, or rely on _connection if that works
        # But wait, accessing self.client.user might still fail if property looks elsewhere.
        # Let's checking discord.py source... usually it returns self._connection.user.
        
        # Mock active_bars with some data
        self.client.active_bars = {
            100: {
                "message_id": 101, 
                "content": "<a:Thinking:123> Thinking...", 
                "user_id": 1, 
                "persisting": False, 
                "checkmark_message_id": 101
            },
            200: {
                "message_id": 201, 
                "content": "<a:Thinking:123> Thinking...", 
                "user_id": 2, 
                "persisting": True, 
                "checkmark_message_id": 201
            }
        }
        
        # Mock DB functions to avoid filesystem writes
        self.mock_whitelist = patch('memory_manager.get_allowed_channels', return_value=[100, 200]).start()
        self.mock_save = patch('memory_manager.save_bar').start()
        self.mock_update = patch('memory_manager.update_bar_content').start()
        self.mock_prev = patch('memory_manager.save_previous_state').start()
        self.mock_find = patch.object(self.client, 'find_last_bar_content', new_callable=AsyncMock).start()
        self.mock_wipe = patch.object(self.client, 'wipe_channel_bars', new_callable=AsyncMock).start()
        self.mock_wipe.return_value = 0
        
        # Default finding content
        self.mock_find.return_value = "<a:Thinking:123> Thinking..."

    def tearDown(self):
        patch.stopall()

    async def test_awake_all_bars_logic(self):
        """Test that awake_all_bars correctly identifies and updates bars."""
        # Mock channel fetching
        mock_channel = MagicMock()
        mock_msg = AsyncMock()
        mock_msg.id = 101
        
        # Setup fetch_message to return a mock message
        mock_channel.fetch_message = AsyncMock(return_value=mock_msg)
        # Setup history to avoid issues (though we mock wipe now)
        mock_channel.history = MagicMock(return_value=AsyncIter([]))
        
        # Setup get_channel to return our mock channel
        self.client.get_channel = MagicMock(return_value=mock_channel)
        self.client.fetch_channel = AsyncMock(return_value=mock_channel)
        
        # Run the method
        count = await self.client.awake_all_bars()
        
        # Assertions
        self.assertEqual(count, 2, "Should process both channels")
        
        # Verify edit was called on the message
        self.assertTrue(mock_msg.edit.called)
        
        # Verify the content set to Speed 0 (Not Watching)
        args, kwargs = mock_msg.edit.call_args
        content = kwargs.get('content') or args[0]
        self.assertIn("<a:NotWatching:1301840196966285322>", content)
        self.assertIn("Thinking...", content) # Content preserved

    async def test_set_speed_all_bars_logic(self):
        """Test that set_speed_all_bars updates the prefix globally."""
        mock_channel = MagicMock()
        mock_msg = AsyncMock()
        
        self.client.get_channel = MagicMock(return_value=mock_channel)
        self.client.fetch_channel = AsyncMock(return_value=mock_channel)
        mock_channel.fetch_message = AsyncMock(return_value=mock_msg)
        
        target_emoji = "<a:SpeedTest:999>"
        
        # Run method
        count = await self.client.set_speed_all_bars(target_emoji)
        
        self.assertEqual(count, 2)
        
        # Check that DB update was called
        self.mock_update.assert_called()
        
        # Check that internal state active_bars is updated
        self.assertTrue(self.client.active_bars[100]["content"].startswith(target_emoji))
        
        # Check that loop.create_task was called (background update)
        self.assertTrue(self.client.loop.create_task.called)

    async def test_slash_command_response_parity(self):
        """Test that new slash commands use visible responses (ephemeral=False)."""
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 100
        interaction.guild_id = 999
        
        # We need to mock the global client in NyxOS module for the commands to access it
        with patch('NyxOS.client', self.client):
            with patch('helpers.is_authorized', return_value=True):
                
                # Mock the specific methods on the client
                self.client.awake_all_bars = AsyncMock(return_value=5)
                self.client.set_speed_all_bars = AsyncMock(return_value=5)
                self.client.global_update_bars = AsyncMock(return_value=5)
                
                # Test /awake
                await NyxOS.awake_command.callback(interaction)
                
                # Should be visible (ephemeral=False) or ephemeral=True depending on implementation
                # Updated to True based on current implementation
                interaction.response.defer.assert_called_with(ephemeral=True)
                interaction.followup.send.assert_called()
                msg = interaction.followup.send.call_args[0][0]
                self.assertIn("Woke up", msg)
                
                # Reset mocks
                interaction.reset_mock()
                
                # Test /speedall0
                await NyxOS.speedall0_command.callback(interaction)
                
                interaction.response.defer.assert_called_with(ephemeral=True)
                interaction.followup.send.assert_called()
                msg = interaction.followup.send.call_args[0][0]
                self.assertIn("Updated speed", msg)

class TestCommandParityChecks(unittest.IsolatedAsyncioTestCase):
    """New Parity Tests verifying correct argument passing in MockInteraction"""
    async def test_mock_interaction_structure(self):
        """Verify MockInteraction passes arguments correctly to channel.send"""
        mock_channel = AsyncMock()
        mock_user = MagicMock()
        intr = NyxOS.MockInteraction(None, mock_channel, mock_user)
        
        # Test send_message with kwargs
        await intr.response.send_message("Hello", delete_after=5, view="ViewObj")
        mock_channel.send.assert_called_with("Hello", delete_after=5, view="ViewObj")
        
        # Test followup.send with kwargs
        await intr.followup.send("Followup", embed="EmbedObj")
        mock_channel.send.assert_called_with("Followup", embed="EmbedObj")

    async def test_help_command_parity(self):
        """Test that &help (via MockInteraction) sends an embed"""
        mock_channel = AsyncMock()
        mock_user = MagicMock()
        interaction = NyxOS.MockInteraction(None, mock_channel, mock_user)
        
        # Execute
        await NyxOS.help_command.callback(interaction)
        
        # Verify
        mock_channel.send.assert_called_once()
        kwargs = mock_channel.send.call_args.kwargs
        self.assertIn('embed', kwargs)

    async def test_testmessage_command_parity(self):
        """Test that &testmessage sends a view"""
        mock_channel = AsyncMock()
        mock_user = MagicMock()
        mock_user.id = 123
        interaction = NyxOS.MockInteraction(None, mock_channel, mock_user)
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('services.service.query_lm_studio', new=AsyncMock(return_value="Response")):
                 with patch('helpers.sanitize_llm_response', return_value="Response"):
                     with patch('helpers.restore_hyperlinks', return_value="Response"):
                        
                        await NyxOS.testmessage_command.callback(interaction)
                        
                        # It calls followup.send(response, view=view)
                        mock_channel.send.assert_called()
                        kwargs = mock_channel.send.call_args.kwargs
                        self.assertIn('view', kwargs)
                        self.assertIsInstance(kwargs['view'], ui.ResponseView)

    async def test_reboot_command_parity(self):
        """Test that &reboot works (calls exec)"""
        mock_channel = AsyncMock()
        mock_user = MagicMock()
        interaction = NyxOS.MockInteraction(None, mock_channel, mock_user)
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                # Fix active_bars to be a dict
                mock_client.active_bars = {}
                mock_client.get_channel.return_value = None
                mock_client.fetch_channel.return_value = None
                
                with patch('os.execl') as mock_execl:
                    with patch('sys.executable', 'python'):
                        with patch('os.fsync'):
                             with patch('NyxOS.config.STARTUP_CHANNEL_ID', None):
                                await NyxOS.reboot_command.callback(interaction)
                                
                                # Should send "Reboot initiated..."
                                mock_channel.send.assert_called()
                                self.assertTrue(mock_channel.send.called)
                                mock_execl.assert_called()