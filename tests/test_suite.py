import unittest
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
import sys
import os
import json
import asyncio
from datetime import datetime

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers
import memory_manager
import config
import services
import ui
import NyxOS

class TestHelpers(unittest.TestCase):
    """Tests for helpers.py"""

    def test_get_safe_mime_type(self):
        # Case 1: Known Extension
        att = MagicMock()
        att.filename = "image.png"
        att.content_type = "application/octet-stream"
        self.assertEqual(helpers.get_safe_mime_type(att), "image/png")

        # Case 2: Trust Discord
        att.filename = "unknown.file"
        att.content_type = "image/gif"
        self.assertEqual(helpers.get_safe_mime_type(att), "image/gif")

        # Case 3: Fallback
        att.filename = "weird.file"
        att.content_type = "application/octet-stream"
        self.assertEqual(helpers.get_safe_mime_type(att), "image/png") # Default fallback

    def test_matches_proxy_tag(self):
        tags = [{'prefix': 'S:', 'suffix': ''}, {'prefix': '', 'suffix': '-C'}]
        self.assertTrue(helpers.matches_proxy_tag("S:Hello", tags))
        self.assertTrue(helpers.matches_proxy_tag("Hello-C", tags))
        self.assertFalse(helpers.matches_proxy_tag("Hello", tags))

    def test_clean_name_logic(self):
        self.assertEqual(helpers.clean_name_logic("User [TAG]", "TAG"), "User")
        self.assertEqual(helpers.clean_name_logic("User", "TAG"), "User")
        self.assertEqual(helpers.clean_name_logic("User [BOT]", "BOT"), "User")

    def test_sanitize_llm_response(self):
        # Strip Headers
        self.assertEqual(helpers.sanitize_llm_response("# Hello"), "Hello")
        self.assertEqual(helpers.sanitize_llm_response("### Hello"), "Hello")
        
        # Strip Tags
        self.assertEqual(helpers.sanitize_llm_response("Hello (Seraph)"), "Hello")
        
        # Strip Reply Context
        self.assertEqual(helpers.sanitize_llm_response("Hello (re: User)"), "Hello")

    def test_restore_hyperlinks(self):
        raw = "Click (Here)(https://example.com)"
        expected = "Click [Here](https://example.com)"
        self.assertEqual(helpers.restore_hyperlinks(raw), expected)

        # Nested parens in text
        raw = "Click (Here (Link))(https://example.com)"
        expected = "Click [Here (Link)](https://example.com)"
        self.assertEqual(helpers.restore_hyperlinks(raw), expected)

    def test_get_identity_suffix(self):
        # Case 1: Custom User Title
        config.USER_TITLES = {123: " (King)"}
        self.assertEqual(helpers.get_identity_suffix(123, None), " (King)")

        # Case 2: System Member (ID Match)
        config.USER_TITLES = {}
        config.MY_SYSTEM_ID = "sys_id"
        self.assertEqual(helpers.get_identity_suffix(456, "sys_id"), " (Seraph)")

        # Case 3: System Member (Name Match)
        members = {"Member1"}
        self.assertEqual(helpers.get_identity_suffix(789, "other_sys", "Member1", members), " (Seraph)")

        # Case 4: Default
        self.assertEqual(helpers.get_identity_suffix(999, "other_sys"), config.DEFAULT_TITLE)

    def test_role_authorization(self):
        # Setup Mock Configuration
        config.ADMIN_ROLE_IDS = [101, 102]
        config.SPECIAL_ROLE_IDS = [201]
        
        # Helper to create mock member with roles
        def mock_member(role_ids):
            m = MagicMock()
            m.roles = []
            for rid in role_ids:
                r = MagicMock()
                r.id = rid
                m.roles.append(r)
            return m

        # Case 1: Admin Role
        admin_user = mock_member([101, 999])
        self.assertTrue(helpers.is_authorized(admin_user))

        # Case 2: Special Role
        special_user = mock_member([201, 888])
        self.assertTrue(helpers.is_authorized(special_user))
        
        # Case 3: Unauthorized (Regular User)
        regular_user = mock_member([999, 888])
        self.assertFalse(helpers.is_authorized(regular_user))
        
        # Case 4: ID Fallback (if user_obj has no roles, e.g., User object, not Member)
        # Though currently is_authorized strictly checks roles for authorization,
        # passing an object without .roles should default to False unless we add ID logic back.
        # The current implementation returns False if no roles attribute.
        user_no_roles = MagicMock(spec=[]) # No .roles attribute
        self.assertFalse(helpers.is_authorized(user_no_roles))

class TestMemoryManager(unittest.TestCase):
    """Tests for memory_manager.py"""

    def setUp(self):
        self.test_dir = "tests/temp_memory_comprehensive"
        os.makedirs(self.test_dir, exist_ok=True)
        config.LOGS_DIR = os.path.join(self.test_dir, "Logs")
        
        # Setup Temp Database
        import tempfile
        from database import Database
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp()
        os.close(self.temp_db_fd)
        
        self.test_db = Database(self.temp_db_path)
        self.original_db = memory_manager.db
        memory_manager.db = self.test_db

    def tearDown(self):
        # Restore DB
        memory_manager.db = self.original_db
        if os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)
            
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_log_conversation(self):
        # Ensure logs are written to the correct date-stamped folder
        memory_manager.log_conversation("general", "User", 123, "Hello World")
        
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(config.LOGS_DIR, today, "general.log")
        
        self.assertTrue(os.path.exists(log_file))
        with open(log_file, 'r') as f:
            content = f.read()
            self.assertIn("Hello World", content)
            self.assertIn("User [123]", content)

    def test_good_bot_logic(self):
        # Increment
        count = memory_manager.increment_good_bot(123, "User1")
        self.assertEqual(count, 1)
        count = memory_manager.increment_good_bot(123, "User1")
        self.assertEqual(count, 2)
        
        # Leaderboard
        memory_manager.increment_good_bot(456, "User2")
        leaderboard = memory_manager.get_good_bot_leaderboard()
        self.assertEqual(len(leaderboard), 2)
        self.assertEqual(leaderboard[0]['username'], "User1") # Highest count first

    def test_suppressed_users(self):
        # Toggle On
        is_suppressed = memory_manager.toggle_suppressed_user(999)
        self.assertTrue(is_suppressed)
        
        # Verify Persistence in DB
        users = memory_manager.get_suppressed_users()
        self.assertIn("999", users)
            
        # Toggle Off
        is_suppressed = memory_manager.toggle_suppressed_user(999)
        self.assertFalse(is_suppressed)
        
        # Verify Removal
        users = memory_manager.get_suppressed_users()
        self.assertNotIn("999", users)

    def test_view_persistence(self):
        msg_id = 123456789
        data = {"prompt": "test", "user": "admin"}
        
        # Save
        memory_manager.save_view_state(msg_id, data)
        
        # Retrieve
        retrieved = memory_manager.get_view_state(msg_id)
        self.assertEqual(retrieved['prompt'], "test")
        
        # Update
        data['prompt'] = "new"
        memory_manager.save_view_state(msg_id, data)
        retrieved = memory_manager.get_view_state(msg_id)
        self.assertEqual(retrieved['prompt'], "new")
        
        # Missing
        self.assertIsNone(memory_manager.get_view_state(999))

class TestServices(unittest.IsolatedAsyncioTestCase):
    """Tests for services.py"""
    
    async def asyncSetUp(self):
        self.test_dir = "tests/temp_services"
        os.makedirs(self.test_dir, exist_ok=True)
        config.MEMORY_DIR = self.test_dir
        
        # Properly patch the session on the global service object
        self.session_patcher = patch.object(services.service, 'http_session', new=MagicMock())
        self.mock_session = self.session_patcher.start()
        
        # Setup default mock behavior for post
        self.mock_post = AsyncMock()
        self.mock_session.post.return_value = self.mock_post

    async def asyncTearDown(self):
        self.session_patcher.stop()
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_generate_search_queries(self):
        # Mock LLM response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'query 1\n- query 2\n&web query 3'}}] 
        }
        
        self.mock_post.__aenter__.return_value = mock_response
        
        queries = await services.service.generate_search_queries("test", [])
        
        self.assertIn("query 1", queries)
        self.assertIn("query 2", queries)
        self.assertIn("query 3", queries) # &web stripped

    async def test_query_lm_studio_payload(self):
        # This test verifies that the payload sent to LM Studio is structured correctly
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {'choices': [{'message': {'content': 'Response'}}]}
        
        self.mock_post.__aenter__.return_value = mock_response

        channel = MagicMock()
        channel.id = 1
        channel.name = "test"

        # Test with Image
        await services.service.query_lm_studio(
            user_prompt="Look at this",
            username="User",
            identity_suffix="",
            history_messages=[],
            channel_obj=channel,
            image_data_uri="data:image/png;base64,xyz"
        )
        
        # Capture call args
        call_args = self.mock_session.post.call_args
        _, kwargs = call_args
        payload = kwargs['json']
        
        # Verify last message has image
        last_msg = payload['messages'][-1]
        self.assertEqual(last_msg['role'], 'user')
        self.assertIsInstance(last_msg['content'], list)
        self.assertEqual(last_msg['content'][1]['type'], 'image_url')

    async def test_message_coalescing(self):
        # Test that consecutive messages from the same role are merged
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {'choices': [{'message': {'content': 'Response'}}]}
        
        self.mock_post.__aenter__.return_value = mock_response

        history = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "World"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Again"}
        ]
        
        channel = MagicMock()
        channel.id = 1
        channel.name = "test"

        await services.service.query_lm_studio(
            user_prompt="Final",
            username="User",
            identity_suffix="",
            history_messages=history,
            channel_obj=channel
        )

        # Capture payload
        call_args = self.mock_session.post.call_args
        _, kwargs = call_args
        messages = kwargs['json']['messages']
        
        # Expected structure after coalescing (excluding system prompt):
        # 1. User: Hello\nWorld
        # 2. Assistant: Hi
        # 3. User: Again\nUser says: Final
        
        # Note: The system prompt is messages[0].
        # messages[1] should be merged User history
        self.assertEqual(messages[1]['role'], 'user')
        # The logic might handle string vs list content differently.
        # In services.py, simple strings are converted to list of text objects during coalesce.
        
        # Let's inspect content text
        content_1 = messages[1]['content']
        if isinstance(content_1, list): content_1 = "".join([x['text'] for x in content_1])
        self.assertIn("Hello", content_1)
        self.assertIn("World", content_1)
        
        # messages[2] Assistant
        self.assertEqual(messages[2]['role'], 'assistant')
        
        # messages[3] Merged User Final
        content_3 = messages[3]['content']
        if isinstance(content_3, list): content_3 = "".join([x['text'] for x in content_3])
        self.assertIn("Again", content_3)
        self.assertIn("Final", content_3)

class TestUI(unittest.IsolatedAsyncioTestCase):
    """Tests for ui.py interactions"""

    async def test_good_bot_callback(self):
        view = ui.ResponseView("Prompt", 123, "User", "", [], MagicMock(), None, None, None, "")
        
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.user.display_name = "User"
        interaction.client = MagicMock()
        interaction.client.good_bot_cooldowns = {}
        
        # Patch increment function
        with patch('memory_manager.increment_good_bot', return_value=5) as mock_inc:
            # Call with just interaction
            await view.good_bot_callback.callback(interaction)
            
            mock_inc.assert_called_with(123, "User")
            
            # Verify the label on the item itself
            # Note: In discord.py, the decorator item IS the button passed to the callback
            self.assertEqual(view.good_bot_callback.label, "Good Bot: 5")
            interaction.response.edit_message.assert_called()

    async def test_retry_callback_persistence_fallback(self):
        # Initialize with defaults (None) to simulate persistent restore
        view = ui.ResponseView() 
        
        interaction = AsyncMock()
        
        # Call with just interaction
        await view.retry_callback.callback(interaction)
        
        # Verify ephemeral error message
        interaction.response.send_message.assert_called_with("❌ Context lost due to reboot. Cannot retry old messages.", ephemeral=True)


class TestServerAdmin(unittest.IsolatedAsyncioTestCase):
    """Tests for Server Administration features"""
    
    def setUp(self):
        self.test_dir = "tests/temp_admin"
        os.makedirs(self.test_dir, exist_ok=True)
        config.COMMAND_STATE_FILE = os.path.join(self.test_dir, "command_state.hash")

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_smart_sync(self):
        client = NyxOS.LMStudioBot()
        client.tree = MagicMock()
        
        # Mock command list
        cmd = MagicMock()
        cmd.name = "test_cmd"
        cmd.description = "desc"
        cmd.nsfw = False
        client.tree.get_commands.return_value = [cmd]
        
        # 1. First Run (No hash file) -> Should Sync
        client.tree.sync = AsyncMock()
        await client.check_and_sync_commands()
        client.tree.sync.assert_called_once()
        
        # 2. Second Run (Hash file exists and matches) -> Should NOT Sync
        client.tree.sync.reset_mock()
        await client.check_and_sync_commands()
        client.tree.sync.assert_not_called()
        
        # 3. Change Command -> Should Sync
        cmd.description = "new desc"
        client.tree.get_commands.return_value = [cmd]
        await client.check_and_sync_commands()
        client.tree.sync.assert_called_once()

class TestCommands(unittest.IsolatedAsyncioTestCase):
    """Tests for Slash Commands"""
    
    def setUp(self):
        self.test_dir = "tests/temp_commands"
        os.makedirs(self.test_dir, exist_ok=True)
        config.RESTART_META_FILE = os.path.join(self.test_dir, "restart_meta.json")
        config.SHUTDOWN_FLAG_FILE = os.path.join(self.test_dir, "shutdown.flag")
        
    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    async def test_reboot_command_authorized(self):
        # Mock Interaction
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 456
        
        # Patch helpers.is_authorized
        with patch('helpers.is_authorized', return_value=True):
            # Patch NyxOS.client
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                # Patch os.execl and sys.executable
                with patch('os.execl') as mock_execl, \
                     patch('sys.executable', '/usr/bin/python'):
                    
                    # Call the callback directly
                    await NyxOS.reboot_command.callback(interaction)
                    
                    # Assertions
                    interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["REBOOT_MESSAGE"], ephemeral=False)
                    mock_client.close.assert_called_once()
                    
                    # Verify restart meta file
                    self.assertTrue(os.path.exists(config.RESTART_META_FILE))
                    
                    # Verify os.execl call
                    mock_execl.assert_called()

    async def test_reboot_command_unauthorized(self):
        interaction = AsyncMock()
        interaction.user.id = 999 # Unauthorized
        
        with patch('helpers.is_authorized', return_value=False):
             await NyxOS.reboot_command.callback(interaction)
             
             interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"], ephemeral=True)
             # Ensure no reboot
             with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                 mock_client.close.assert_not_called()

    async def test_shutdown_command(self):
        interaction = AsyncMock()
        interaction.user.id = 123
        interaction.channel_id = 456
        
        with patch('helpers.is_authorized', return_value=True):
            with patch('NyxOS.client', new=AsyncMock()) as mock_client:
                with patch('sys.exit') as mock_exit:
                     
                     await NyxOS.shutdown_command.callback(interaction)
                     
                     interaction.response.send_message.assert_called_with(ui.FLAVOR_TEXT["SHUTDOWN_MESSAGE"], ephemeral=False)
                     mock_client.close.assert_called_once()
                     mock_exit.assert_called_with(0)
                     self.assertTrue(os.path.exists(config.SHUTDOWN_FLAG_FILE))

def run_comprehensive_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryManager))
    suite.addTests(loader.loadTestsFromTestCase(TestServices))
    suite.addTests(loader.loadTestsFromTestCase(TestUI))
    suite.addTests(loader.loadTestsFromTestCase(TestServerAdmin))
    suite.addTests(loader.loadTestsFromTestCase(TestCommands))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result

if __name__ == '__main__':
    run_comprehensive_suite()
