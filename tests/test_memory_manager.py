import pytest
from unittest.mock import MagicMock, patch, mock_open
import memory_manager
import asyncio
import datetime

class TestMemoryManager:

    @pytest.mark.asyncio
    async def test_write_context_buffer(self):
        # Mock the DB instance used in memory_manager
        mock_db = MagicMock()
        with patch('memory_manager.db', mock_db):
            
            # Test Case 1: Standard Text Message
            messages = [
                {'role': 'user', 'content': 'Hello [World]'},
                {'role': 'system', 'content': 'System'}
            ]
            channel_id = "123"
            channel_name = "general"
            
            await memory_manager.write_context_buffer(messages, channel_id, channel_name)
            
            # Verify DB call
            mock_db.update_context_buffer.assert_called_once()
            args = mock_db.update_context_buffer.call_args[0]
            # args: (channel_id, channel_name, full_content)
            content_sent = args[2]
            
            assert "=== MEMORY BUFFER FOR #general (123) ===" in content_sent
            assert "[USER]" in content_sent
            assert "Hello (World)" in content_sent # Bracket sanitization check
            assert "[SYSTEM]" in content_sent

    @pytest.mark.asyncio
    async def test_write_context_buffer_images(self):
        mock_db = MagicMock()
        with patch('memory_manager.db', mock_db):
            # Test Case 2: Image Message
            messages = [
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Look at this'},
                    {'type': 'image_url', 'url': 'http://...'}
                ]}
            ]
            
            await memory_manager.write_context_buffer(messages, "123", "gen")
            
            args = mock_db.update_context_buffer.call_args[0]
            content_sent = args[2]
            
            assert "Look at this (IMAGE DATA SENT TO AI)" in content_sent

    @pytest.mark.asyncio
    async def test_write_context_buffer_append(self):
        mock_db = MagicMock()
        with patch('memory_manager.db', mock_db):
            # Test Case 3: Append Response
            response_text = "I agree [with] you."
            
            await memory_manager.write_context_buffer([], "123", "gen", append_response=response_text)
            
            mock_db.append_to_context_buffer.assert_called_once()
            args = mock_db.append_to_context_buffer.call_args[0]
            # args: (channel_id, content)
            content_sent = args[1]
            
            assert "[ASSISTANT_REPLY]" in content_sent
            assert "I agree (with) you." in content_sent

    def test_log_conversation(self):
        # Mock datetime to have consistent timestamp
        mock_dt = MagicMock()
        mock_dt.now.return_value.strftime.side_effect = lambda fmt: "2025-11-29" if "%Y" in fmt else "12:00:00"
        
        with patch('memory_manager.datetime', mock_dt), \
             patch('builtins.open', mock_open()) as mocked_file, \
             patch('os.makedirs') as mock_dirs, \
             patch('os.path.exists', return_value=False): # Simulate new file
            
            channel = "debug-logs"
            user = "Tester"
            uid = "999"
            content = "Test Message"
            
            memory_manager.log_conversation(channel, user, uid, content)
            
            # Verify Directory Creation
            mock_dirs.assert_called()
            
            # Verify File Writes
            # First write: Header (since we simulated file not exists)
            # Second write: Log content
            
            assert mocked_file.call_count == 2
            handle = mocked_file()
            
            # Check content of writes
            # 1. Header
            handle.write.assert_any_call(f"=== LOG STARTED: 2025-11-29 ===\nSYSTEM PROMPT:\n{memory_manager.config.SYSTEM_PROMPT_TEMPLATE}\n====================================\n\n")
            
            # 2. Message
            handle.write.assert_any_call("[12:00:00] Tester [999]: Test Message\n")

