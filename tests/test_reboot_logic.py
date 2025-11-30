import unittest
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
import sys
import os
import config
import ui
import NyxOS
import helpers
import json

class TestRebootLogic(unittest.IsolatedAsyncioTestCase):
    """Tests for the shared perform_reboot logic in NyxOS.py"""
    
    def setUp(self):
        self.test_dir = "tests/temp_reboot"
        os.makedirs(self.test_dir, exist_ok=True)
        # Override configs to use test dir
        config.RESTART_META_FILE = os.path.join(self.test_dir, "restart_meta.json")
        config.STARTUP_CHANNEL_ID = 12345 # Set a dummy ID

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_perform_reboot_slash_context(self):
        """Test reboot triggered via Slash Command"""
        interaction = MagicMock() # Main interaction object is usually sync-ish access to attrs
        interaction.user.id = 111
        interaction.channel_id = 222
        interaction.guild_id = 333
        
        # Setup Response (Sync object with Async methods)
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        
        # Followup is usually separate
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        
        # Mock Client
        mock_client = AsyncMock()
        mock_client.active_bars = {}
        # Mock Console Channel
        console_ch = AsyncMock()
        console_ch.id = config.STARTUP_CHANNEL_ID
        # Mock Send Return Value (Message)
        mock_msg = MagicMock()
        mock_msg.id = 1001 # Concrete ID
        console_ch.send.return_value = mock_msg
        
        mock_client.fetch_channel.return_value = console_ch
        
        with patch('NyxOS.client', mock_client):
            with patch('NyxOS.os.execl') as mock_execl:
                with patch('NyxOS.sys.executable', 'python'):
                    with patch('NyxOS.os.fsync'):
                        
                        # EXECUTE
                        await NyxOS.perform_reboot(interaction=interaction)
                        
                        # VERIFY                      
                        # 1. Defer                    
                        interaction.response.defer.assert_called_with(ephemeral=True)                        
                        # 2. Console Messages
                        console_ch.purge.assert_called()
                        self.assertGreaterEqual(console_ch.send.call_count, 3)
                        
                        # 3. Followup with link
                        interaction.followup.send.assert_called()
                        args = interaction.followup.send.call_args[0][0]
                        self.assertIn("Reboot initiated", args)
                        
                        # 4. Meta File
                        self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                        with open(config.RESTART_META_FILE, 'r') as f:
                            data = json.load(f)
                            self.assertEqual(data['channel_id'], config.STARTUP_CHANNEL_ID)
                            
                        # 5. Close and Exec
                        mock_client.close.assert_called_once()
                        mock_execl.assert_called()

    async def test_perform_reboot_prefix_context(self):
        """Test reboot triggered via Prefix Command (&reboot)"""
        message = AsyncMock()
        message.author.id = 111
        message.channel.id = 222
        message.guild.id = 333
        
        mock_client = AsyncMock()
        mock_client.active_bars = {}
        console_ch = AsyncMock()
        console_ch.id = config.STARTUP_CHANNEL_ID
        mock_msg = MagicMock()
        mock_msg.id = 1002
        console_ch.send.return_value = mock_msg
        mock_client.fetch_channel.return_value = console_ch
        
        with patch('NyxOS.client', mock_client):
            with patch('NyxOS.os.execl') as mock_execl:
                with patch('NyxOS.sys.executable', 'python'):
                    with patch('NyxOS.os.fsync'):
                        
                        # EXECUTE
                        await NyxOS.perform_reboot(message=message)
                        
                        # VERIFY
                        # 1. Console Messages (Same as slash)
                        console_ch.purge.assert_called()
                        self.assertGreaterEqual(console_ch.send.call_count, 3)
                        
                        # 2. Message Handling (Different from slash)
                        # Should delete the user's command message
                        message.delete.assert_called()
                        # Should send temporary confirmation to chat
                        message.channel.send.assert_called()
                        
                        # 3. Meta File
                        self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                        
                        # 4. Close and Exec
                        mock_client.close.assert_called_once()
                        mock_execl.assert_called()

    async def test_perform_reboot_no_console(self):
        """Test fallback behavior when no console channel is configured"""
        config.STARTUP_CHANNEL_ID = None # Disable console
        
        interaction = MagicMock()
        interaction.channel_id = 222
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
        
        mock_client = AsyncMock()
        mock_client.active_bars = {}
        
        with patch('NyxOS.client', mock_client):
            with patch('NyxOS.os.execl'):
                with patch('NyxOS.sys.executable', 'python'):
                     with patch('NyxOS.os.fsync'):
                        
                        await NyxOS.perform_reboot(interaction=interaction)
                        
                        # Should NOT try to fetch console
                        mock_client.fetch_channel.assert_not_called()
                        
                        # Should post full text to interaction channel (fallback)
                        interaction.followup.send.assert_called()
                        args = interaction.followup.send.call_args[0][0]
                        self.assertIn("(Console not configured)", args)
                        
                        # Meta file should point to interaction channel
                        with open(config.RESTART_META_FILE, 'r') as f:
                            data = json.load(f)
                            self.assertEqual(data['channel_id'], 222)

