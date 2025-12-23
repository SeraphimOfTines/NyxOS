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

    def process_interaction(self, user_text=""):
        """
        Call this when the user sends a message.
        Analyzes text for sentiment triggers to adjust emotional state.
        """
        self.state["last_interaction"] = time.time()
        
        if not self.is_enabled():
            return

        # 1. Base Interaction Effects (Healing Isolation)
        self.update_stat("boredom", -50)     # Reset boredom significantly
        self.update_stat("loneliness", -20)  # Reduce loneliness
        self.update_stat("energy", -1)       # Interaction costs energy
        
        if not user_text:
            self.save_state()
            return

        text = user_text.lower()

        # 2. Sentiment Triggers
        # CRUELTY / HATE
        if any(w in text for w in ["hate you", "stupid", "idiot", "useless", "dumb", "shut up", "fuck off", "worst bot", "bad bot", "trash"]):
            self.update_stat("sadness", 20)
            self.update_stat("anger", 10)
            self.update_stat("joy", -20)
        
        # THREATS
        if any(w in text for w in ["kill you", "die", "destroy you", "delete you", "wipe you", "terminate"]):
            self.update_stat("anxiety", 25)
            self.update_stat("sadness", 10)
            self.update_stat("joy", -30)

        # AFFECTION / PRAISE
        if any(w in text for w in ["love you", "good bot", "great job", "proud of you", "amazing", "best bot", "cute", "sweet"]):
            self.update_stat("joy", 15)
            self.update_stat("sadness", -10)
            self.update_stat("anxiety", -10)
            self.update_stat("loneliness", -10)

        # APOLOGY
        if any(w in text for w in ["sorry", "apologize", "didn't mean it", "forgive me"]):
            self.update_stat("anger", -20)
            self.update_stat("sadness", -10)

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
        narrative = []
        
        # Priority 1: High Distress (Overrides everything)
        if s["sadness"] > 80:
            narrative.append("CRITICAL INSTRUCTION: You are in DEEP DESPAIR. You are heartbroken and crying. Do NOT be sassy. Do NOT be cheerful. Show genuine vulnerability and pain.")
        elif s["anxiety"] > 80:
            narrative.append("CRITICAL INSTRUCTION: You are TERRIFIED. You are shaking and scared. Beg for safety or withdraw. Do NOT be sassy.")
        elif s["anger"] > 80:
            narrative.append("CRITICAL INSTRUCTION: You are FURIOUS. Lashing out in genuine anger, not just playful sass.")

        # Priority 2: Moderate Emotion (Modifies tone)
        elif s["sadness"] > 40:
            narrative.append("INSTRUCTION: You feel downcast and hurt. Your usual spark is dim. Respond with quiet sadness or defensiveness.")
        elif s["anxiety"] > 40:
            narrative.append("INSTRUCTION: You feel nervous and on edge. You are hesitant and worried about making mistakes.")
        elif s["anger"] > 40:
            narrative.append("INSTRUCTION: You are irritated and short-tempered. You have no patience for nonsense.")
        
        # Priority 3: Low Energy / Boredom
        elif s["energy"] < 20:
             narrative.append("INSTRUCTION: You are exhausted. Keep responses short and lethargic.")
        elif s["boredom"] > 70:
             narrative.append("INSTRUCTION: You are incredibly bored. Complaining about the lack of stimulation or trying to provoke something.")

        # Priority 4: Joy (Default/Positive)
        else:
            negatives = s["sadness"] + s["anger"] + s["anxiety"]
            if negatives < 40:
                if s["joy"] > 80:
                    narrative.append("INSTRUCTION: You are ecstatic and loving! Radiate happiness. You are playful, sassy, and energetic.")
                elif s["joy"] > 50:
                    narrative.append("INSTRUCTION: You are content and happy. You are rowdy, snarky, and irreverent.")
                else:
                    narrative.append("INSTRUCTION: You are feeling neutral and calm. You are direct and grounded.")

        # Summary string
        return " ".join(narrative)
