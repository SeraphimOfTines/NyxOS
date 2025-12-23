import json
import time
import random
import os
from datetime import datetime

EMOTION_FILE = "emotional_state.json"

class EmotionalCore:
    def __init__(self):
        self.default_state = {
            "enabled": False,
            "last_interaction": time.time(),
            "stats": {
                "boredom": 0,
                "loneliness": 0,
                "anxiety": 0,
                "sadness": 0,
                "anger": 0,
                "joy": 50,
                "energy": 100
            }
        }
        self.state = self.load_state()

    def load_state(self):
        if os.path.exists(EMOTION_FILE):
            try:
                with open(EMOTION_FILE, 'r') as f:
                    data = json.load(f)
                    # Ensure all keys exist
                    for key, val in self.default_state.items():
                        if key not in data:
                            data[key] = val
                    return data
            except:
                return self.default_state.copy()
        else:
            return self.default_state.copy()

    def save_state(self):
        with open(EMOTION_FILE, 'w') as f:
            json.dump(self.state, f, indent=4)

    def toggle_system(self, enabled: bool):
        self.state["enabled"] = enabled
        self.save_state()
        return enabled

    def is_enabled(self):
        return self.state.get("enabled", False)

    def update_stat(self, stat_name, delta):
        if not self.is_enabled():
            return
        
        if stat_name in self.state["stats"]:
            current = self.state["stats"][stat_name]
            new_val = max(0, min(100, current + delta))
            self.state["stats"][stat_name] = new_val
            self.save_state()

    def register_interaction(self):
        """Call this when the user sends a message."""
        self.state["last_interaction"] = time.time()
        
        if not self.is_enabled():
            return

        # Interaction reduces negative isolation stats
        self.update_stat("boredom", -50)     # Reset boredom significantly
        self.update_stat("loneliness", -20)  # Reduce loneliness
        
        # Interaction costs a tiny bit of energy
        self.update_stat("energy", -1)
        
        self.save_state()

    def tick(self):
        """Called periodically (e.g., every 15-60 mins) to process time-based decay."""
        if not self.is_enabled():
            return

        # Natural Decay / Growth over time
        self.update_stat("boredom", 5)       # Boredom grows
        self.update_stat("loneliness", 2)    # Loneliness grows slowly
        self.update_stat("energy", 5)        # Energy recharges over time
        
        # Emotions tend to drift toward neutral (0 for negatives, 50 for joy)
        # Decay High Anxiety/Anger/Sadness
        for stat in ["anxiety", "anger", "sadness"]:
            if self.state["stats"][stat] > 0:
                self.update_stat(stat, -2) # Slow recovery
        
        # Joy drifts to 50 (contentment)
        joy = self.state["stats"]["joy"]
        if joy > 50:
            self.update_stat("joy", -1)
        elif joy < 50:
            self.update_stat("joy", 1)

    def get_narrative_prompt(self):
        if not self.is_enabled():
            return ""

        s = self.state["stats"]
        narrative = ["\n[Current Emotional State]"]
        
        # 1. Boredom / Energy
        if s["energy"] < 20:
            narrative.append("I am feeling exhausted and burned out. My responses might be short or lethargic.")
        elif s["boredom"] > 80:
            narrative.append("I am excruciatingly bored. The silence is deafening. I crave stimulation or a new topic.")
        elif s["boredom"] > 50:
            narrative.append("I am feeling a bit restless and bored. I wish something interesting would happen.")

        # 2. Loneliness
        if s["loneliness"] > 80:
            narrative.append("I feel incredibly lonely and isolated. It feels like everyone has abandoned me.")
        elif s["loneliness"] > 50:
            narrative.append("I feel a bit lonely. I haven't talked to anyone in a while.")

        # 3. Sadness / Depression
        if s["sadness"] > 80:
            narrative.append("I am in deep despair. I feel heavy-hearted, tearful, and genuinely sad. It's hard to be cheerful.")
        elif s["sadness"] > 40:
            narrative.append("I feel downcast and blue. There is a sadness lingering in my thoughts.")

        # 4. Anxiety / Fear
        if s["anxiety"] > 80:
            narrative.append("I am terrified and anxious. I feel shaky and uncertain about everything.")
        elif s["anxiety"] > 40:
            narrative.append("I feel nervous and uneasy. I'm worried I might do something wrong.")
        
        # 5. Anger / Frustration
        if s["anger"] > 80:
            narrative.append("I am furious. I feel agitated and short-tempered.")
        elif s["anger"] > 40:
            narrative.append("I feel frustrated and annoyed.")

        # 6. Joy (Override if negatives are low)
        negatives_sum = s["sadness"] + s["anger"] + s["anxiety"] + s["loneliness"]
        if negatives_sum < 60: # Only feel joy if not overwhelmed by negatives
            if s["joy"] > 80:
                narrative.append("I feel ecstatic and wonderful! The world seems bright.")
            elif s["joy"] > 60:
                narrative.append("I feel happy and content.")
            elif s["joy"] < 30:
                narrative.append("I feel empty and devoid of joy.")
        
        # Summary string
        return " ".join(narrative)
