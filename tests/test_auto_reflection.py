import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import NyxOS

class TestAutoReflection:
    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock(spec=NyxOS.LMStudioBot)
        bot.auto_reflection_enabled = False
        bot.last_reflection_date = None
        return bot

    @pytest.mark.asyncio
    async def test_reflection_disabled(self, mock_bot):
        mock_bot.auto_reflection_enabled = False
        
        # Access the underlying coroutine of the loop
        task_coro = NyxOS.LMStudioBot.daily_reflection_task.coro
        
        with patch('NyxOS.self_reflection.process_missed_days', new_callable=AsyncMock) as mock_process:
             await task_coro(mock_bot)
             mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_reflection_enabled_not_midnight(self, mock_bot):
        mock_bot.auto_reflection_enabled = True
        
        mock_now = datetime(2023, 1, 1, 12, 0, 0) # Noon
        
        with patch('NyxOS.datetime') as mock_dt_mod:
            mock_dt_mod.datetime.now.return_value = mock_now
            
            task_coro = NyxOS.LMStudioBot.daily_reflection_task.coro
            with patch('NyxOS.self_reflection.process_missed_days', new_callable=AsyncMock) as mock_process:
                await task_coro(mock_bot)
                mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_reflection_enabled_midnight_run(self, mock_bot):
        mock_bot.auto_reflection_enabled = True
        mock_bot.last_reflection_date = None
        
        mock_now = datetime(2023, 1, 1, 0, 1, 0) # 00:01
        
        with patch('NyxOS.datetime') as mock_dt_mod:
             mock_dt_mod.datetime.now.return_value = mock_now
             
             task_coro = NyxOS.LMStudioBot.daily_reflection_task.coro
             with patch('NyxOS.self_reflection.process_missed_days', new_callable=AsyncMock) as mock_process:
                await task_coro(mock_bot)
                mock_process.assert_called_once()
                assert mock_bot.last_reflection_date == mock_now.date()

    @pytest.mark.asyncio
    async def test_reflection_enabled_midnight_already_run(self, mock_bot):
        mock_bot.auto_reflection_enabled = True
        mock_now = datetime(2023, 1, 1, 0, 1, 0)
        mock_bot.last_reflection_date = mock_now.date() # Already ran today
        
        with patch('NyxOS.datetime') as mock_dt_mod:
             mock_dt_mod.datetime.now.return_value = mock_now
             
             task_coro = NyxOS.LMStudioBot.daily_reflection_task.coro
             with patch('NyxOS.self_reflection.process_missed_days', new_callable=AsyncMock) as mock_process:
                await task_coro(mock_bot)
                mock_process.assert_not_called()
