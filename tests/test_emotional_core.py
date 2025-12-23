import unittest
import os
import json
from emotional_core import EmotionalCore, EMOTION_FILE

class TestEmotionalCore(unittest.TestCase):
    def setUp(self):
        # Backup existing state if any
        if os.path.exists(EMOTION_FILE):
            os.rename(EMOTION_FILE, EMOTION_FILE + ".bak")
        
    def tearDown(self):
        # Restore backup
        if os.path.exists(EMOTION_FILE + ".bak"):
            if os.path.exists(EMOTION_FILE):
                os.remove(EMOTION_FILE)
            os.rename(EMOTION_FILE + ".bak", EMOTION_FILE)
        elif os.path.exists(EMOTION_FILE):
            os.remove(EMOTION_FILE)

    def test_energy_tick(self):
        ec = EmotionalCore()
        ec.toggle_system(True)
        # Set energy to 50
        ec.update_stat("energy", -50) # 100 - 50 = 50
        self.assertEqual(ec.state["stats"]["energy"], 50)
        
        # Tick should add 10
        ec.tick()
        self.assertEqual(ec.state["stats"]["energy"], 60)

    def test_interaction_cost_and_reward(self):
        ec = EmotionalCore()
        ec.toggle_system(True)
        
        # Neutral interaction: Cost 1
        start_energy = ec.state["stats"]["energy"]
        ec.process_interaction("Hello")
        self.assertEqual(ec.state["stats"]["energy"], start_energy - 1)
        
        # Praise interaction: Cost 1 + Reward 5 = Net +4
        # Lower energy first to avoid cap
        ec.update_stat("energy", -50)
        current_energy = ec.state["stats"]["energy"]
        
        ec.process_interaction("Good bot")
        # -1 for interaction, +5 for praise = +4
        self.assertEqual(ec.state["stats"]["energy"], current_energy + 4)

if __name__ == '__main__':
    unittest.main()
