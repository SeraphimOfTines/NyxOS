import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import config
import ui
import NyxOS
import json

class TestRebootLogic(unittest.IsolatedAsyncioTestCase):
    """Tests for the perform_shutdown_sequence logic in NyxOS.py"""
    
    def setUp(self):
        self.test_dir = "tests/temp_reboot"
        os.makedirs(self.test_dir, exist_ok=True)
        # Override configs to use test dir
        config.RESTART_META_FILE = os.path.join(self.test_dir, "restart_meta.json")
        config.SHUTDOWN_FLAG_FILE = os.path.join(self.test_dir, "shutdown.flag")
        config.STARTUP_CHANNEL_ID = 12345

        # Create a mock client that uses the REAL perform_shutdown_sequence method
        self.mock_client = MagicMock(spec=NyxOS.LMStudioBot)
        self.mock_client.perform_shutdown_sequence = NyxOS.LMStudioBot.perform_shutdown_sequence.__get__(self.mock_client, NyxOS.LMStudioBot)
        
        # Mock async methods called within perform_shutdown_sequence
        self.mock_client.close = AsyncMock()
        self.mock_client.fetch_channel = AsyncMock()
        self.mock_client.get_channel = MagicMock(return_value=None)
        self.mock_client.startup_header_msg = None
        self.mock_client.startup_bar_msg = None
        self.mock_client.console_progress_msgs = []
        
        # Helper attributes expected by the method
        self.mock_client.user.id = 999

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

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
        
        with patch('time.sleep'): # Skip sleep
            with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=True)
                
                # Verify UI updates
                h_msg.edit.assert_called()
                b_msg.edit.assert_called()
                
                # Verify Meta Write
                self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                with open(config.RESTART_META_FILE, 'r') as f:
                    data = json.load(f)
                    self.assertEqual(data['header_msg_id'], 100)
                
                # Verify Close and Exit
                self.mock_client.close.assert_called_once()
                mock_exit.assert_called_with(0)

    async def test_shutdown_sequence_logic(self):
        """Test shutdown logic (restart=False)"""
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        
        with patch('time.sleep'):
             with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=False)
                
                # Verify Flag Write
                self.assertTrue(os.path.exists(config.SHUTDOWN_FLAG_FILE))
                
                # Verify Close and Exit
                self.mock_client.close.assert_called_once()
                mock_exit.assert_called_with(0)

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
        
        with patch('time.sleep'):
             with patch('sys.exit') as mock_exit:
                
                await self.mock_client.perform_shutdown_sequence(interaction, restart=True)
                
                # Should send fallback message
                interaction.followup.send.assert_called()
                
                # Meta should point to interaction channel
                self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                with open(config.RESTART_META_FILE, 'r') as f:
                    data = json.load(f)
                    self.assertEqual(data['channel_id'], 999)
                
                mock_exit.assert_called_with(0)