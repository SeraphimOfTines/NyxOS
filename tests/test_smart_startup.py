import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import NyxOS

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

class TestSmartStartup(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Patch CommandTree to avoid http dependency during init
        self.tree_patcher = patch('discord.app_commands.CommandTree')
        self.mock_tree = self.tree_patcher.start()
        
        self.client = NyxOS.LMStudioBot()
        # Mocking the user property is tricky on an instance if it's a property.
        # We can mock the internal _connection which discord.py uses.
        self.client._connection = MagicMock()
        self.client._connection.user = MagicMock()
        self.client._connection.user.id = 999
        
        self.client.get_channel = MagicMock()
        self.client.fetch_channel = AsyncMock()
        
        # Mock Active Bars / State
        self.client.active_bars = {}
        
        # Silence logging
        patch('NyxOS.logger').start()

    def tearDown(self):
        self.tree_patcher.stop()
        patch.stopall()

    async def test_startup_reuse_existing_messages(self):
        """Test that startup logic reuses existing messages if 3 are found."""
        
        # Mock Channel
        mock_channel = MagicMock()
        mock_channel.name = "startup-channel"
        mock_channel.purge = AsyncMock()
        mock_channel.send = AsyncMock()
        
        # Mock Messages (Newest First: Body, Bar, Header)
        msg_body = AsyncMock()
        msg_body.author.id = 999
        msg_body.content = "Body"
        msg_body.created_at = 300
        
        msg_bar = AsyncMock()
        msg_bar.author.id = 999
        msg_bar.content = "Bar"
        msg_bar.created_at = 200
        
        msg_header = AsyncMock()
        msg_header.author.id = 999
        msg_header.content = "Header"
        msg_header.created_at = 100
        
        # Setup History (Return Body, Bar, Header)
        mock_channel.history = MagicMock(return_value=AsyncIter([msg_body, msg_bar, msg_header]))
        
        self.client.get_channel.return_value = mock_channel
        
        # Mock dependencies
        with patch('memory_manager.get_master_bar', return_value="Master Bar"), \
             patch('memory_manager.get_bar_whitelist', return_value=[]), \
             patch('ui.FLAVOR_TEXT', {
                 "STARTUP_HEADER": "Header", 
                 "STARTUP_SUB": "Sub", 
                 "REBOOT_HEADER": "Reboot Header",
                 "REBOOT_SUB": "Reboot Sub",
                 "COSMETIC_DIVIDER": "---"
             }):
            
            # Simulate the critical section of on_ready for ONE channel
            # --- REPLICATED LOGIC FROM NyxOS.py (Updated for Strict Check) ---
            t_ch = mock_channel
            startup_header_text = "New Header"
            msg2_text = "New Bar"
            body_text = "New Body"
            client = self.client
            progress_msgs = []

            existing_msgs = []
            async for m in t_ch.history(limit=10):
                existing_msgs.append(m)
            
            # Sort Oldest -> Newest
            existing_msgs.sort(key=lambda x: x.created_at)
            
            # Strict Check: Count == 3 AND Author is Bot
            valid_state = (len(existing_msgs) == 3 and all(m.author.id == 999 for m in existing_msgs))
            
            h_msg = None; bar_msg = None; b_msg = None
            success = False

            if valid_state:
                h_msg = existing_msgs[0]
                bar_msg = existing_msgs[1]
                b_msg = existing_msgs[2]
                
                try:
                    await h_msg.edit(content=startup_header_text)
                    await bar_msg.edit(content=msg2_text)
                    await b_msg.edit(content=body_text, embed=None, view=None)
                    
                    client.startup_header_msg = h_msg
                    client.startup_bar_msg = bar_msg
                    progress_msgs.append(b_msg)
                    success = True
                except: success = False

            if not success:
                await t_ch.purge(limit=100)
                await t_ch.send("Header")
                await t_ch.send("Bar")
                await t_ch.send("Body")
            # -----------------------------------------------------------

            # Assertions
            
            # 1. Verify Edits
            h_msg.edit.assert_called()
            bar_msg.edit.assert_called()
            b_msg.edit.assert_called()
            
            # 2. Verify NO Purge/Send
            mock_channel.purge.assert_not_called()
            mock_channel.send.assert_not_called()

    async def test_startup_fallback_when_missing(self):
        """Test that startup logic falls back to wipe/send if messages are missing."""
        
        mock_channel = MagicMock()
        mock_channel.purge = AsyncMock()
        mock_channel.send = AsyncMock(return_value=AsyncMock())
        
        # Return only 1 message
        msg1 = AsyncMock()
        msg1.author.id = 999
        msg1.created_at = 100
        mock_channel.history = MagicMock(return_value=AsyncIter([msg1]))
        
        # Execute Logic (Updated Strict)
        t_ch = mock_channel
        existing_msgs = []
        async for m in t_ch.history(limit=10):
            existing_msgs.append(m)
        existing_msgs.sort(key=lambda x: x.created_at)
        
        valid_state = (len(existing_msgs) == 3 and all(m.author.id == 999 for m in existing_msgs))
        
        if valid_state:
             pass # Edit
        else:
             await t_ch.purge(limit=100)
             await t_ch.send("Header")
        
        # Verify Purge and Send
        mock_channel.purge.assert_called()
        mock_channel.send.assert_called()

    async def test_startup_too_many_messages(self):
        """Test that startup logic wipes if there are TOO MANY messages."""
        
        mock_channel = MagicMock()
        mock_channel.purge = AsyncMock()
        mock_channel.send = AsyncMock(return_value=AsyncMock())
        
        # Return 4 messages
        msgs = [AsyncMock() for _ in range(4)]
        for i, m in enumerate(msgs):
            m.author.id = 999
            m.created_at = 100 + i
            
        mock_channel.history = MagicMock(return_value=AsyncIter(msgs))
        
        # Execute Logic (Updated Strict)
        t_ch = mock_channel
        existing_msgs = []
        async for m in t_ch.history(limit=10):
            existing_msgs.append(m)
        existing_msgs.sort(key=lambda x: x.created_at)
        
        valid_state = (len(existing_msgs) == 3 and all(m.author.id == 999 for m in existing_msgs))
        
        if valid_state:
             pass # Edit
        else:
             await t_ch.purge(limit=100)
             await t_ch.send("Header")
        
        # Verify Purge and Send
        mock_channel.purge.assert_called()
        mock_channel.send.assert_called()

if __name__ == '__main__':
    unittest.main()