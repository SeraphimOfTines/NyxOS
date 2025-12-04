import sys
import threading
import asyncio
from datetime import datetime
import time
import discord

# Mock Classes for Terminal Interaction

class TerminalUser:
    def __init__(self):
        self.id = 0
        self.name = "Admin"
        self.display_name = "Admin"
        self.discriminator = "0000"
        self.bot = False
        self.mention = "@Admin"
        self.avatar = None
        self.roles = []
    def __str__(self):
        return self.name

class TerminalChannel:

    def __init__(self, client):

        self.id = 0

        self.name = "terminal"

        self.client = client

        self.guild = None

        self.mention = "#terminal"

        self.messages = [] # In-memory history

    

    async def send(self, content=None, **kwargs):

        print("\n" + "="*30)

        if content:

            print(f"[NyxOS]: {content}")

        

        if kwargs.get('embed'):

            emb = kwargs['embed']

            print(f"[Embed]: {emb.title or ''} - {emb.description or ''}")

            for f in emb.fields:

                print(f"  - {f.name}: {f.value}")

        

        if kwargs.get('view'):

             print("[Interactive View Attached] (Buttons not supported in terminal)")

             

        if kwargs.get('file'):

             print("[File Attachment] (Cannot display in terminal)")



        print("="*30 + "\n")

        

        # Return a mock message so the bot doesn't crash if it tries to use it

        msg = TerminalMessage(self.client, content, self.client.user, self)

        self.messages.append(msg)

        return msg



    def history(self, limit=10, before=None):
        # Return reversed list (newest first) for history iterator
        msgs = list(reversed(self.messages))
        if limit: msgs = msgs[:limit]
        
        class AsyncIter:
            def __init__(self, items): self.items = items
            def __aiter__(self): return self
            async def __anext__(self): 
                if not self.items: raise StopAsyncIteration
                return self.items.pop(0)
        return AsyncIter(msgs)
    
    async def fetch_message(self, id):
        return None
    async def trigger_typing(self):
        pass
    
    def typing(self):
        class TypingContext:
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): pass
        return TypingContext()

class TerminalMessage:
    def __init__(self, client, content, author, channel):
        self.id = int(time.time() * 1000)
        self.content = content or ""
        self.clean_content = content or ""
        self.author = author
        self.channel = channel
        self.guild = None
        self.reference = None
        self.mentions = []
        self.role_mentions = []
        self.embeds = []
        self.webhook_id = None
        self.attachments = []
        self.created_at = datetime.now()
        self.components = []
        self.flags = discord.MessageFlags._from_value(0)
        self.type = discord.MessageType.default
        
    async def reply(self, content=None, **kwargs):
        return await self.channel.send(content, **kwargs)
    
    async def edit(self, **kwargs):
        if 'content' in kwargs:
            print(f"[Message Edited]: {kwargs['content']}")

    async def delete(self):
        print("[Message Deleted]")
        
    async def add_reaction(self, emoji):
        print(f"[Reaction Added]: {emoji}")

def start_terminal_listener(loop, callback):
    """
    Starts a thread that listens to stdin and calls the callback on the event loop.
    """
    def listener():
        print("\n💻 Terminal Interface Active. Type commands (/cmd) or chat directly.\n")
        while True:
            try:
                line = sys.stdin.readline()
                if not line: break # EOF
                line = line.strip()
                if line:
                    asyncio.run_coroutine_threadsafe(callback(line), loop)
            except Exception as e:
                print(f"Terminal Error: {e}")
                break
                
    t = threading.Thread(target=listener, daemon=True)
    t.start()
