import time
import unittest
from unittest.mock import MagicMock
from volition import VolitionManager

class TestVolitionLogic(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.vm = VolitionManager(self.mock_client)
        # Manually set interests for testing
        self.vm.interests = {"nyx", "bot", "code"}
        self.vm.activity_window = 180
        
    def test_semantic_score_time_window(self):
        # 1. Add an "interesting" message that is RECENT
        msg_recent = {
            "author": "User",
            "content": "I love nyx code bot",
            "timestamp": time.time(),
            "channel_id": 123
        }
        self.vm.buffer.append(msg_recent)
        
        score_recent = self.vm.calculate_semantic_score()
        self.assertGreater(score_recent, 0.0, "Recent interesting message should generate score")
        
        # 2. Add an "interesting" message that is OLD
        msg_old = {
            "author": "User",
            "content": "I love nyx code bot",
            "timestamp": time.time() - 200, # Older than 180s window
            "channel_id": 123
        }
        self.vm.buffer.clear()
        self.vm.buffer.append(msg_old)
        
        score_old = self.vm.calculate_semantic_score()
        self.assertEqual(score_old, 0.0, "Old interesting message should NOT generate score")

    def test_urge_math_quiet_monologue(self):
        # Setup Quiet State
        self.vm.buffer.clear() # No activity
        self.vm.last_speech_time = time.time() - 400 # Long ago (no cooldown)
        
        # Mock RNG to return HIGH chaos
        self.vm.rng_source.random = MagicMock(return_value=0.95)
        
        urge = self.vm.calculate_urge()
        
        # Base (0.2) + Activity(0) + Semantic(0) + Chaos(0.5 * 0.95 = 0.475) = 0.675
        # Threshold is 0.65
        self.assertGreater(urge, self.vm.threshold, "High chaos should trigger urge in silence")
        
    def test_urge_math_quiet_low_chaos(self):
        # Setup Quiet State
        self.vm.buffer.clear()
        self.vm.last_speech_time = time.time() - 400
        
        # Mock RNG to return LOW chaos
        self.vm.rng_source.random = MagicMock(return_value=0.1)
        
        urge = self.vm.calculate_urge()
        
        # Base (0.2) + Chaos(0.5 * 0.1 = 0.05) = 0.25
        self.assertLess(urge, self.vm.threshold, "Low chaos should NOT trigger urge in silence")

if __name__ == '__main__':
    unittest.main()
