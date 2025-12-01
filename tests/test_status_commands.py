import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import ui
import NyxOS

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestStatusCommands(unittest.IsolatedAsyncioTestCase):
    """Tests for Status Commands like angel and darkangel"""
    
    async def test_angel_command(self):
        interaction = AsyncMock()
        
        # Patch NyxOS.client
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            # Call the callback
            await NyxOS.angel_command.callback(interaction)
            
            # Verify replace_bar_content was called with ui.ANGEL_CONTENT
            mock_client.replace_bar_content.assert_called_once_with(interaction, ui.ANGEL_CONTENT)
            # Verify update_bar_prefix was NOT called (old behavior)
            mock_client.update_bar_prefix.assert_not_called()

    async def test_darkangel_command(self):
        interaction = AsyncMock()
        
        # Patch NyxOS.client
        with patch('NyxOS.client', new=AsyncMock()) as mock_client:
            # Call the callback
            await NyxOS.darkangel_command.callback(interaction)
            
            # Verify replace_bar_content was called with ui.DARK_ANGEL_CONTENT
            mock_client.replace_bar_content.assert_called_once_with(interaction, ui.DARK_ANGEL_CONTENT)

if __name__ == "__main__":
    unittest.main()
