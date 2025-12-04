import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os
import asyncio

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Do NOT mock discord if it's available in venv
# sys.modules['discord'] = MagicMock() ...

import NyxOS

class TestCleanupCrash(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_race_condition(self):
        """
        Simulates a race condition where the bar is removed from active_bars
        during the async fetch/delete operations in cleanup_old_bars.
        """
        client = NyxOS.client
        # Reset active_bars
        client.active_bars = {}
        
        channel = MagicMock()
        channel.id = 12345
        
        # Setup active_bars with an entry
        client.active_bars = {
            12345: {
                "message_id": 999,
                "checkmark_message_id": 888
            }
        }
        
        # Mock fetch_message
        mock_msg = MagicMock()
        mock_msg.delete = AsyncMock()

        async def side_effect(*args, **kwargs):
            # Simulate race condition: remove key while "fetching"
            if 12345 in client.active_bars:
                # We manually delete to simulate the race condition
                # This mimics the "del self.active_bars[channel.id]" happening elsewhere or being stale
                # Actually, the crash was because cleanup_old_bars ITSELF tries to delete it later.
                # So if we remove it here, cleanup_old_bars will fail if it uses 'del'.
                del client.active_bars[12345]
            return mock_msg

        # Use MagicMock with async side_effect
        channel.fetch_message = MagicMock(side_effect=side_effect)
        
        # Mock memory_manager
        with patch('memory_manager.delete_bar') as mock_delete:
            # Run cleanup
            try:
                await client.cleanup_old_bars(channel)
            except KeyError:
                self.fail("cleanup_old_bars raised KeyError!")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.fail(f"cleanup_old_bars raised unexpected exception: {e}")
            
            # Verify it's gone
            self.assertNotIn(12345, client.active_bars)

if __name__ == '__main__':
    unittest.main()
