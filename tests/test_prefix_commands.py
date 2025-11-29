import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

# --- MOCKING DEPENDENCIES ---
# We must mock 'discord' and others BEFORE importing NyxOS
mock_discord = MagicMock()

class DummyClient:
    def __init__(self, intents=None, **kwargs):
        self.loop = MagicMock()
        
    def event(self, coro):
        return coro
        
    async def close(self): pass
    async def wait_until_ready(self): pass
    def is_closed(self): return False
    def get_channel(self, id): return MagicMock()
    async def fetch_channel(self, id): return MagicMock()

mock_discord.Client = DummyClient
# Fix: CommandTree must be a callable that returns a mock, not the MagicMock class itself
mock_discord.app_commands.CommandTree = MagicMock(return_value=MagicMock())
mock_discord.Intents.default = MagicMock
sys.modules["discord"] = mock_discord
sys.modules["discord.app_commands"] = mock_discord.app_commands

sys.modules["config"] = MagicMock()
sys.modules["config"].LOGS_DIR = "/tmp"
sys.modules["config"].BOT_ROLE_IDS = []
sys.modules["config"].ADMIN_ROLE_IDS = []
sys.modules["config"].SPECIAL_ROLE_IDS = []
sys.modules["config"].MY_SYSTEM_ID = "sysid"
sys.modules["config"].CONTEXT_WINDOW = 5

sys.modules["helpers"] = MagicMock()
sys.modules["helpers"].is_authorized = MagicMock(return_value=True)
sys.modules["helpers"].get_safe_mime_type = MagicMock(return_value="text/plain")
sys.modules["helpers"].clean_name_logic = MagicMock(return_value="User")
sys.modules["helpers"].get_identity_suffix = MagicMock(return_value="")
sys.modules["helpers"].sanitize_llm_response = MagicMock(side_effect=lambda x: x)
sys.modules["helpers"].restore_hyperlinks = MagicMock(side_effect=lambda x: x)
sys.modules["helpers"].matches_proxy_tag = MagicMock(return_value=False)

sys.modules["services"] = MagicMock()
sys.modules["services"].service = MagicMock()
sys.modules["services"].service.get_pk_message_data = AsyncMock(return_value=(None, None, None, None, None, None))
sys.modules["services"].service.get_pk_user_data = AsyncMock(return_value=None)
sys.modules["services"].service.get_system_proxy_tags = AsyncMock(return_value=[])
sys.modules["services"].service.check_local_pk_system = AsyncMock(return_value=False)

sys.modules["memory_manager"] = MagicMock()
sys.modules["memory_manager"].get_server_setting = MagicMock(return_value=False)
sys.modules["memory_manager"].get_allowed_channels = MagicMock(return_value=[999])
sys.modules["memory_manager"].save_bar = MagicMock()

sys.modules["ui"] = MagicMock()
sys.modules["ui"].FLAVOR_TEXT = {"CHECKMARK_EMOJI": "✅", "WAKE_WORD_REACTION": "👀", "GOOD_BOT_REACTION": "💙"}
sys.modules["ui"].BAR_PREFIX_EMOJIS = ["<a:Thinking:123>", "✅"]
sys.modules["ui"].StatusBarView = MagicMock()

# Import NyxOS after mocking
import NyxOS

class TestPrefixCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = NyxOS.client
        self.client.user = MagicMock()
        self.client.user.id = 88888
        self.client.user.display_name = "NyxOS"
        self.client.user.name = "nyxos"
        
        self.client.active_bars = {}
        self.client.bar_drop_cooldowns = {}
        self.client.find_last_bar_content = AsyncMock(return_value=None)
        self.client.cleanup_old_bars = AsyncMock()
        self.client.drop_status_bar = AsyncMock()
        self.client.processing_locks = set()
        self.client.abort_signals = set()
        self.client.channel_cutoff_times = {}
        self.client.boot_cleared_channels = set()
        
        self.message = MagicMock()
        self.message.id = 1001
        self.message.author.id = 12345
        self.message.author.bot = False
        self.message.channel.id = 999
        self.message.channel.send = AsyncMock(return_value=MagicMock(id=2001))
        self.message.delete = AsyncMock()
        self.message.content = ""
        self.message.webhook_id = None
        self.message.attachments = []
        self.message.mentions = []
        self.message.role_mentions = []
        self.message.reference = None
        
    async def test_bar_command(self):
        self.message.content = "&bar test content"
        await NyxOS.on_message(self.message)
        
        self.message.delete.assert_called_once()
        self.client.cleanup_old_bars.assert_called_with(self.message.channel)
        self.message.channel.send.assert_called()
        self.assertIn(999, self.client.active_bars)
        self.assertEqual(self.client.active_bars[999]["content"], "test content")

    async def test_b_alias(self):
        self.message.content = "&b alias test"
        await NyxOS.on_message(self.message)
        self.message.delete.assert_called_once()
        self.assertIn(999, self.client.active_bars)
        self.assertEqual(self.client.active_bars[999]["content"], "alias test")

    async def test_drop_command(self):
        self.client.active_bars[999] = {"content": "foo", "persisting": False}
        self.message.content = "&drop"
        await NyxOS.on_message(self.message)
        self.message.delete.assert_called_once()
        self.client.drop_status_bar.assert_called_with(999, move_check=True)

    async def test_d_alias(self):
        self.client.active_bars[999] = {"content": "foo", "persisting": False}
        self.message.content = "&d"
        await NyxOS.on_message(self.message)
        self.message.delete.assert_called_once()
        self.client.drop_status_bar.assert_called_with(999, move_check=True)

    async def test_dropcheck_command(self):
        self.client.active_bars[999] = {
            "content": "foo", 
            "message_id": 100, 
            "checkmark_message_id": 200,
            "persisting": False
        }
        mock_msg = MagicMock()
        mock_msg.edit = AsyncMock()
        self.message.channel.fetch_message = AsyncMock(return_value=mock_msg)
        
        self.message.content = "&dropcheck"
        await NyxOS.on_message(self.message)
        self.message.delete.assert_called_once()

    async def test_c_alias(self):
        self.client.active_bars[999] = {
            "content": "foo", 
            "message_id": 100, 
            "checkmark_message_id": 200,
            "persisting": False
        }
        mock_msg = MagicMock()
        mock_msg.edit = AsyncMock()
        self.message.channel.fetch_message = AsyncMock(return_value=mock_msg)
        
        self.message.content = "&c"
        await NyxOS.on_message(self.message)
        self.message.delete.assert_called_once()

if __name__ == '__main__':
    unittest.main()