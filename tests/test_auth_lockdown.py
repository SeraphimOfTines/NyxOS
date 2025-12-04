import unittest
import discord
import sys
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import ui
import helpers

class TestAuthLockdown(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_interaction = MagicMock(spec=discord.Interaction)
        self.mock_interaction.user = MagicMock(spec=discord.User)
        self.mock_interaction.user.id = 99999 # Random ID
        self.mock_interaction.response = MagicMock()
        self.mock_interaction.response.send_message = AsyncMock()
        self.mock_interaction.response.edit_message = AsyncMock()
        self.mock_interaction.response.defer = AsyncMock()
        self.mock_interaction.followup = MagicMock()
        self.mock_interaction.followup.send = AsyncMock()
        self.mock_interaction.message = MagicMock()
        self.mock_interaction.message.delete = AsyncMock()
        self.mock_interaction.client = MagicMock()
        self.mock_interaction.client.perform_shutdown_sequence = AsyncMock()
        self.mock_interaction.client.idle_all_bars = AsyncMock()
        self.mock_interaction.client.sleep_all_bars = AsyncMock()

    @patch('helpers.is_authorized')
    async def test_status_bar_auth_fail(self, mock_is_auth):
        """Test StatusBarView buttons block non-admins."""
        mock_is_auth.return_value = False
        
        view = ui.StatusBarView("content", 123, 456)
        button = MagicMock()
        
        # Test check_auth directly
        result = await view.check_auth(self.mock_interaction, button)
        
        self.assertFalse(result)
        self.mock_interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)

    @patch('helpers.is_authorized')
    async def test_status_bar_auth_pass(self, mock_is_auth):
        """Test StatusBarView buttons allow admins."""
        mock_is_auth.return_value = True
        
        view = ui.StatusBarView("content", 123, 456)
        button = MagicMock()
        
        result = await view.check_auth(self.mock_interaction, button)
        
        self.assertTrue(result)
        self.mock_interaction.response.send_message.assert_not_called()

    @patch('helpers.is_admin')
    async def test_backup_cancel_auth_fail(self, mock_is_admin):
        """Test BackupControlView cancel blocks non-admins."""
        mock_is_admin.return_value = False
        
        view = ui.BackupControlView(cancel_event=MagicMock())
        
        # Find the button
        btn = discord.utils.get(view.children, custom_id="backup_cancel_btn")
        self.assertIsNotNone(btn)
        
        # Invoke callback bound to the button
        # The callback signature is (interaction, button)
        # _ViewCallback likely expects just interaction if already bound?
        await btn.callback(self.mock_interaction)
        
        self.mock_interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
        self.assertFalse(view.cancelled)

    @patch('helpers.is_admin')
    async def test_backup_cancel_auth_pass(self, mock_is_admin):
        """Test BackupControlView cancel allows admins."""
        mock_is_admin.return_value = True
        
        view = ui.BackupControlView(cancel_event=MagicMock())
        
        # Find the button
        btn = discord.utils.get(view.children, custom_id="backup_cancel_btn")
        self.assertIsNotNone(btn)
        
        # Invoke callback
        await btn.callback(self.mock_interaction)
        
        # Should proceed
        self.mock_interaction.response.send_message.assert_not_called()
        self.assertTrue(view.cancelled)