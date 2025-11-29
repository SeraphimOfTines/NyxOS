import asyncio
import unittest.mock
import sys
import os

# Ensure we can import local modules
sys.path.append(os.getcwd())

import command_handler
import config
import helpers

# Mock Discord Objects
class MockMessage:
    def __init__(self, content, author_id):
        self.content = content
        self.author = unittest.mock.MagicMock()
        self.author.id = author_id
        self.channel = unittest.mock.MagicMock()
        self.channel.send = unittest.mock.AsyncMock()
        self.guild_permissions = unittest.mock.MagicMock()
        self.guild_permissions.administrator = True # Grant admin for test

async def run_diagnostic():
    print("--- DIAGNOSTIC START ---")
    
    # 1. Check if &debugtest is in the handler code
    if "&debugtest" in open("command_handler.py").read():
        print("✅ command_handler.py contains '&debugtest' logic.")
    else:
        print("❌ command_handler.py is MISSING '&debugtest' logic!")

    # 2. Simulate the command
    # We need a valid admin ID. We'll borrow one from config or just mock the auth check.
    # Since we can't easily know your ID, we'll mock is_authorized to True.
    original_auth = helpers.is_authorized
    helpers.is_authorized = lambda x: True
    
    print("\n[Test 1] Simulating '&debugtest'...")
    msg = MockMessage("&debugtest", 12345)
    client = unittest.mock.MagicMock()
    
    try:
        handled = await command_handler.handle_prefix_command(client, msg)
        if handled:
            print("✅ handle_prefix_command returned True.")
            # Check if it tried to send a response
            if msg.channel.send.called:
                args = msg.channel.send.call_args[0]
                print(f"✅ Bot tried to send: {args[0]}")
            else:
                print("⚠️ Handler returned True, but no message was sent.")
        else:
            print("❌ handle_prefix_command returned False (Command not recognized).")
            
    except Exception as e:
        print(f"❌ Exception during execution: {e}")
    
    # Restore auth
    helpers.is_authorized = original_auth
    print("\n--- DIAGNOSTIC END ---")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
