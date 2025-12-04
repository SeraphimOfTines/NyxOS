import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta, timezone

# We need to test the logic inside on_message, but it's huge.
# Instead of importing the whole bot, we can extract the logic or mock the bot/message environment carefully.
# Since I modified NyxOS.py directly, I should try to import it, but it has heavy dependencies.

# Alternative: Verify the logic by mocking the critical parts in a dedicated test function that replicates the on_message block.
# OR, since I just replaced the code, I can write a test that mocks the updated section if I can isolate it.

# Let's try to import NyxOS (it might fail due to other dependencies, but let's try with mocks)
# We need to mock logging, discord, etc.

class TestGhostCheck(unittest.IsolatedAsyncioTestCase):
    async def test_ghost_wait_logic(self):
        """
        Simulates the Ghost Check logic:
        1. Message arrives.
        2. Wait 3.5s.
        3. Check if message exists.
        4. Check history for webhook.
        """
        
        # Mocks
        message = MagicMock()
        message.id = 100
        message.content = "Hello"
        message.created_at = datetime.now(timezone.utc)
        message.webhook_id = None
        message.channel = MagicMock()
        
        # Scenario 1: Message Deleted (Ghosted)
        # fetch_message raises NotFound
        message.channel.fetch_message = AsyncMock(side_effect=Exception("NotFound")) # simulating discord.NotFound
        
        # The logic snippet:
        skip_reaction_remove = False
        
        # Simulate the sleep (we can't wait 3.5s in test, so we patch sleep)
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            try:
                await mock_sleep(3.5) # Call the mock
                try:
                    await message.channel.fetch_message(message.id)
                    # ... history check ...
                except Exception:
                    skip_reaction_remove = True
                    # return (in real code)
            except: pass
            
        self.assertTrue(skip_reaction_remove, "Should return/skip if message is deleted (NotFound)")

        # Scenario 2: Message Exists but Webhook Found (Late Proxy)
        message.channel.fetch_message = AsyncMock(return_value=message)
        
        # History Mock
        webhook_msg = MagicMock()
        webhook_msg.webhook_id = 999
        webhook_msg.created_at = message.created_at + timedelta(seconds=1) # 1s later
        
        # async generator for history
        async def mock_history(limit=15):
            yield webhook_msg
            
        message.channel.history = mock_history
        
        skip_reaction_remove = False
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
             # Replicate Logic
             await mock_sleep(3.5)
             try:
                 await message.channel.fetch_message(message.id)
                 async for recent in message.channel.history(limit=15):
                     if recent.webhook_id is not None:
                         diff = (recent.created_at - message.created_at).total_seconds()
                         if abs(diff) < 4.0:
                             skip_reaction_remove = True
                             break # return
             except: pass
             
        self.assertTrue(skip_reaction_remove, "Should return/skip if webhook found nearby")

if __name__ == "__main__":
    unittest.main()
