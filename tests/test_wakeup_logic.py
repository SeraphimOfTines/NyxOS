import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS
import discord

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Helper for async iteration

class TestWakeupLogic(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.client = NyxOS.LMStudioBot()
        # Mock internal connection
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 999
        self.client.active_bars = {'100': {}} # Dummy entry for deletion test

    async def test_sync_removes_missing_bars(self):
        """Test that syncconsole removes bars if missing/404."""
        
        # Mock DB
        with patch('memory_manager.get_bar_whitelist', return_value=['100']), \
             patch('memory_manager.get_channel_location', return_value=(123, 123)), \
             patch('NyxOS.client', self.client), \
             patch('helpers.is_authorized', return_value=True), \
             patch('asyncio.sleep'): # Skip delay
             
            # Mock Channel fetch to raise NotFound
            mock_ch = AsyncMock()
            mock_ch.fetch_message.side_effect = discord.NotFound(MagicMock(), "Gone")
            
            # Setup client mocks
            self.client.get_channel = MagicMock(return_value=mock_ch)
            self.client.fetch_channel = AsyncMock(return_value=mock_ch)
            self.client.update_console_status = AsyncMock()
            
            with patch('memory_manager.remove_bar_whitelist') as mock_remove:
                with patch('memory_manager.delete_bar') as mock_delete:
                    
                    # Run Sync
                    interaction = AsyncMock()
                    await NyxOS.syncconsole_command.callback(interaction)
                    
                    # Verify Removal
                    mock_remove.assert_called_with(100)
                    mock_delete.assert_called_with(100)
                    # Verify active_bars update
                    self.assertNotIn(100, self.client.active_bars)

if __name__ == '__main__':
    unittest.main()