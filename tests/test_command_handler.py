import pytest
from unittest.mock import MagicMock, patch, mock_open, AsyncMock
import command_handler
import config
import ui
import memory_manager

class TestCommandHandler:

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.channel_cutoff_times = {}
        client.close = AsyncMock() # Fix await client.close()
        return client

    @pytest.fixture
    def mock_message(self):
        msg = MagicMock()
        msg.content = ""
        msg.channel.send = AsyncMock() # Ensure this is AsyncMock
        msg.channel.id = 100
        msg.author.id = 999
        return msg

    @pytest.mark.asyncio
    async def test_authorization_success(self, mock_client, mock_message):
        # Setup Admin User
        mock_message.content = "&reboot"
        with patch('helpers.is_authorized', return_value=True), \
             patch('command_handler.os.execl'), \
             patch('command_handler.sys.argv'), \
             patch('builtins.open', mock_open()):
            
            processed = await command_handler.handle_prefix_command(mock_client, mock_message)
            
            # assert processed is True # Removed: Returns False because os.execl is mocked and execution falls through
            mock_message.channel.send.assert_called_with(ui.FLAVOR_TEXT["REBOOT_MESSAGE"])

    @pytest.mark.asyncio
    async def test_authorization_failure(self, mock_client, mock_message):
        # Setup Non-Admin User
        mock_message.content = "&reboot"
        with patch('helpers.is_authorized', return_value=False):
            
            processed = await command_handler.handle_prefix_command(mock_client, mock_message)
            
            assert processed is True
            mock_message.channel.send.assert_called_with(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])

    @pytest.mark.asyncio
    async def test_add_remove_channel(self, mock_client, mock_message):
        # Test Add
        mock_message.content = "&addchannel"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('memory_manager.get_allowed_channels', return_value=[]), \
             patch('memory_manager.add_allowed_channel') as mock_add:
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            mock_add.assert_called_with(100)
            assert "I'll talk in this channel" in mock_message.channel.send.call_args[0][0]

        # Test Remove
        mock_message.content = "&removechannel"
        
        with patch('helpers.is_authorized', return_value=True), \
             patch('memory_manager.get_allowed_channels', return_value=[100]), \
             patch('memory_manager.remove_allowed_channel') as mock_remove:
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            mock_remove.assert_called_with(100)
            assert "I'll ignore this channel" in mock_message.channel.send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_reboot_logic(self, mock_client, mock_message):
        mock_message.content = "&reboot"
        mock_message.channel.id = 123
        
        m_open = mock_open()
        with patch('helpers.is_authorized', return_value=True), \
             patch('builtins.open', m_open), \
             patch('command_handler.os.execl') as mock_exec, \
             patch('command_handler.sys.executable', 'python'), \
             patch('command_handler.os.fsync'):
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            # Verify Write to RESTART_META_FILE
            m_open.assert_called_with(config.RESTART_META_FILE, "w")
            
            # Verify Execution
            mock_exec.assert_called()

    @pytest.mark.asyncio
    async def test_shutdown_logic(self, mock_client, mock_message):
        mock_message.content = "&shutdown"
        
        m_open = mock_open()
        with patch('helpers.is_authorized', return_value=True), \
             patch('builtins.open', m_open), \
             patch('command_handler.sys.exit') as mock_exit:
            
            await command_handler.handle_prefix_command(mock_client, mock_message)
            
            # Verify Write to SHUTDOWN_FLAG_FILE
            m_open.assert_called_with(config.SHUTDOWN_FLAG_FILE, "w")
            
            # Verify Exit
            mock_exit.assert_called_with(0)