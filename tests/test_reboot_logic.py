import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import json

class AsyncIter:
    def __init__(self, items):
        self.items = list(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)

class TestRebootLogic(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.patcher = patch('discord.Client.__init__')
        self.mock_init = self.patcher.start()
        self.mock_init.return_value = None
        
        # Need to mock app_commands.CommandTree because LMStudioBot inits it
        with patch('discord.app_commands.CommandTree'):
             from NyxOS import LMStudioBot
             self.mock_client = LMStudioBot()
             
        self.mock_client._connection = MagicMock()
        self.mock_client._connection.user = MagicMock()
        self.mock_client._connection.user.id = 12345
        self.mock_client.close = AsyncMock()
        
        # Mock Channel
        self.mock_channel = AsyncMock()
        # Fix: history returns an AsyncIter, not a Coroutine
        self.mock_channel.history = MagicMock(return_value=AsyncIter([]))
        
        self.mock_client.fetch_channel = AsyncMock(return_value=self.mock_channel)
        
        # Clean up temp files
        if os.path.exists(config.RESTART_META_FILE):
            os.remove(config.RESTART_META_FILE)
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            os.remove(config.SHUTDOWN_FLAG_FILE)

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(config.RESTART_META_FILE):
            os.remove(config.RESTART_META_FILE)
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            os.remove(config.SHUTDOWN_FLAG_FILE)

    async def test_reboot_sequence_with_console(self):
        """Test reboot logic when console messages are cached"""
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        
        # Mock cached messages
        h_msg = AsyncMock()
        h_msg.channel.id = 12345
        h_msg.id = 100
        b_msg = AsyncMock()
        b_msg.channel.id = 12345
        b_msg.id = 101
        
        self.mock_client.startup_header_msg = h_msg
        self.mock_client.startup_bar_msg = b_msg
        self.mock_client.fetch_channel.return_value = h_msg.channel
        
        with patch('asyncio.sleep'): # Skip sleep
            with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=True)
                
                # Verify UI updates
                # h_msg should be edited twice (Powering Down, then Offline)
                self.assertEqual(h_msg.edit.call_count, 2)
                
                # b_msg (Bar) should NOT be edited (Preserve Status Icons)
                b_msg.edit.assert_not_called()
                
                # Verify Meta Write
                self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                with open(config.RESTART_META_FILE, 'r') as f:
                    data = json.load(f)
                    self.assertEqual(data['header_msg_id'], 100)
                
                # Verify Close (Exit is handled by main loop now)
                self.mock_client.close.assert_called_once()

    async def test_shutdown_sequence_logic(self):
        """Test shutdown logic (restart=False)"""
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        
        with patch('asyncio.sleep'):
             with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=False)
                
                # Verify Flag Write
                self.assertTrue(os.path.exists(config.SHUTDOWN_FLAG_FILE))
                
                # Verify Close (Exit is handled by main loop now)
                self.mock_client.close.assert_called_once()

    async def test_reboot_fallback_no_ui(self):
        """Test reboot fallback when UI not found"""
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.channel.id = 999
        
        self.mock_client.startup_header_msg = None
        
        # Mock fetch_channel to fail or return None for startup channel
        self.mock_client.fetch_channel.side_effect = Exception("Not Found")
        
        with patch('asyncio.sleep'):
             with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=True)
                
                # Should send fallback message
                interaction.followup.send.assert_called()
                
                # Meta should point to interaction channel
                self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                with open(config.RESTART_META_FILE, 'r') as f:
                    data = json.load(f)
                    self.assertEqual(data['channel_id'], 999)