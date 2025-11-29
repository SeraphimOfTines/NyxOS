import unittest
from unittest.mock import MagicMock, patch, AsyncMock, call
import sys
import os
import asyncio
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import NyxOS
import ui
import config
import memory_manager

class TestWakeCommands(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        # Mock Client User Property
        self.user_patcher = patch('discord.Client.user', new_callable=MagicMock)
        self.mock_user_prop = self.user_patcher.start()
        self.mock_user = MagicMock()
        self.mock_user.id = 12345
        self.mock_user_prop.__get__ = MagicMock(return_value=self.mock_user)
        
        self.client = NyxOS.LMStudioBot()
        
        # Mock State
        self.client.active_bars = {}
        self.client.active_views = {}
        
        # Mock Dependencies
        self.mock_get_allowed = patch('memory_manager.get_allowed_channels').start()
        self.mock_get_all_bars = patch('memory_manager.get_all_bars').start()
        self.mock_save_bar = patch('memory_manager.save_bar').start()
        self.mock_wipe = patch.object(self.client, 'wipe_channel_bars', new=AsyncMock()).start()
        self.mock_fetch_channel = patch.object(self.client, 'fetch_channel', new=AsyncMock()).start()
        self.mock_get_channel = patch.object(self.client, 'get_channel').start()
        
        # Default allowed channels
        self.mock_get_allowed.return_value = [100, 200]

    async def asyncTearDown(self):
        patch.stopall()

    async def test_run_wake_routine_success(self):
        """Test standard successful wakeup of multiple channels."""
        
        # Mock Channel 100
        ch100 = MagicMock()
        ch100.id = 100
        ch100.mention = "<#100>"
        ch100.history = MagicMock(return_value=self._mock_history_iterator(
            content=f"{ui.BAR_PREFIX_EMOJIS[0]} Bar1 {ui.FLAVOR_TEXT['CHECKMARK_EMOJI']}"
        ))
        ch100.send = AsyncMock(return_value=MagicMock(id=101, jump_url="http://url1"))
        
        # Mock Channel 200
        ch200 = MagicMock()
        ch200.id = 200
        ch200.mention = "<#200>"
        ch200.history = MagicMock(return_value=self._mock_history_iterator(
            content="Just some chat text" # No bar here
        ))
        ch200.send = AsyncMock()

        # Setup get_channel return values
        def get_channel_side_effect(cid):
            if cid == 100: return ch100
            if cid == 200: return ch200
            return None
        self.mock_get_channel.side_effect = get_channel_side_effect
        
        # Run
        count = await self.client.run_wake_routine()
        
        # Verifications
        # Channel 100 should be woken
        self.mock_wipe.assert_any_call(ch100)
        ch100.send.assert_called_once()
        args, _ = ch100.send.call_args
        self.assertIn(ui.BAR_PREFIX_EMOJIS[2], args[0]) # Speed 0 (NotWatching)
        self.assertIn("Bar1", args[0])
        self.assertEqual(self.client.active_bars[100]['content'], args[0])
        
        # Channel 200 should NOT be woken (no bar found)
        # self.mock_wipe.assert_any_call(ch200) # Wait, wipe is called BEFORE scan? 
        # Re-reading run_wake_routine:
        # Phase 1: Scan -> bars_to_wake.append
        # Phase 2: For item in bars_to_wake -> wipe -> send
        # So ch200 should NOT be wiped or sent to if no bar found.
        
        # Verify ch200 calls
        # It was scanned (history called)
        ch200.history.assert_called() 
        # But not wiped or sent
        calls_to_200_wipe = [c for c in self.mock_wipe.mock_calls if c.args and c.args[0] == ch200]
        self.assertEqual(len(calls_to_200_wipe), 0)
        ch200.send.assert_not_called()
        
        self.assertEqual(count, 1)

    async def test_run_wake_routine_channel_fetch_fail(self):
        """Test robustness when a channel cannot be found."""
        self.mock_get_allowed.return_value = [300]
        
        # get_channel returns None
        self.mock_get_channel.return_value = None
        
        # fetch_channel raises NotFound
        self.mock_fetch_channel.side_effect = discord.NotFound(MagicMock(), "Not Found")
        
        # Run
        count = await self.client.run_wake_routine()
        
        self.assertEqual(count, 0)
        # Should not crash

    async def test_run_wake_routine_send_fail(self):
        """Test robustness when sending the new bar fails (e.g. Permissions)."""
        ch100 = MagicMock()
        ch100.id = 100
        ch100.history = MagicMock(return_value=self._mock_history_iterator(
            content=f"{ui.BAR_PREFIX_EMOJIS[0]} Bar1"
        ))
        # Send raises Forbidden
        ch100.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "No Perms"))
        
        self.mock_get_channel.return_value = ch100
        
        # Run
        count = await self.client.run_wake_routine()
        
        # Should fail to register bar
        self.assertNotIn(100, self.client.active_bars)
        self.assertEqual(count, 0) # Not counted as woken

    async def test_run_wake_persistence_preservation(self):
        """Ensure 'persisting' flag is preserved when waking."""
        ch100 = MagicMock()
        ch100.id = 100
        ch100.history = MagicMock(return_value=self._mock_history_iterator(
            content=f"{ui.BAR_PREFIX_EMOJIS[0]} Bar1"
        ))
        ch100.send = AsyncMock(return_value=MagicMock(id=999))
        self.mock_get_channel.return_value = ch100
        
        # Pre-existing active bar with persistence=True
        self.client.active_bars[100] = {"persisting": True}
        
        await self.client.run_wake_routine()
        
        # Verify new state
        self.assertTrue(self.client.active_bars[100]['persisting'])
        
        # Verify Save Call arguments
        # args: channel_id, guild_id, msg_id, user_id, content, persisting
        save_call = self.mock_save_bar.call_args
        self.assertTrue(save_call[0][5]) # 6th arg is persisting

    async def test_slash_wake_command(self):
        """Test the /wake slash command interaction."""
        interaction = AsyncMock()
        interaction.user.id = 999
        
        # Mock run_wake_routine on client
        self.client.run_wake_routine = AsyncMock(return_value=5)
        
        # Patch unauthorized
        with patch('helpers.is_authorized', return_value=False):
            await NyxOS.wake_command.callback(interaction)
            interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
            self.client.run_wake_routine.assert_not_called()

        # Patch authorized
        with patch('helpers.is_authorized', return_value=True):
            # We need to set the client on the interaction or patch NyxOS.client
            # The command uses `client.run_wake_routine`. `client` is global in NyxOS.py
            # We must patch `NyxOS.client`
            with patch('NyxOS.client', self.client):
                await NyxOS.wake_command.callback(interaction)
                
                interaction.response.defer.assert_called_with(ephemeral=False)
                self.client.run_wake_routine.assert_called_once()
                
                # Verify status callback updates
                # The command defines an inner async function `update_status` passed to `run_wake_routine`
                # We can simulate calling it
                status_cb = self.client.run_wake_routine.call_args[0][0]
                await status_cb("Status Update")
                interaction.edit_original_response.assert_called_with(content="Status Update")

    # --- Helper ---
    async def _mock_history_iterator(self, content):
        """Async iterator for history."""
        msg = MagicMock()
        msg.author.id = 12345 # Bot ID
        msg.content = content
        yield msg

if __name__ == '__main__':
    unittest.main()
