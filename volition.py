import time
import random
import logging
import asyncio
from collections import deque, Counter
import re
import config
import services
import memory_manager
import vector_store

logger = logging.getLogger("NyxOS.Volition")

class VolitionManager:
    def __init__(self, client):
        self.client = client
        self.buffer = deque(maxlen=20) # Short-term memory
        self.last_speech_time = time.time() - 300 # Start fresh (no cooldown penalty)
        self.rng_source = random.SystemRandom() # Best software RNG available
        
        # State
        self.mood = "neutral"
        self.current_urge = 0.0
        self.enabled = config.VOLITION_ENABLED if hasattr(config, "VOLITION_ENABLED") else False
        
        # Tuning (Adjusted for better responsiveness)
        self.base_urge = 0.2       # Was 0.1
        self.threshold = 1.0       # Was 0.65 (Raised to calm her down)
        self.decay_rate = 0.05 
        
        # Weights
        self.w_activity = 0.6      # Was 0.4
        self.w_chaos = 0.4         # Was 0.3
        self.activity_window = 180 # Seconds (Was 60)
        
        # Semantic Interest
        self.interests = set()
        self.update_interests_from_prompt()

    def update_interests_from_prompt(self):
        """Extracts key nouns/verbs from the system prompt to form dynamic interests."""
        try:
            text = config.SYSTEM_PROMPT
            if not text: return

            # Basic Stopwords (can be expanded)
            stopwords = {
                "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", 
                "it", "for", "not", "on", "with", "he", "as", "you", "do", "at", 
                "this", "but", "his", "by", "from", "they", "we", "say", "her", 
                "she", "or", "an", "will", "my", "one", "all", "would", "there", 
                "their", "what", "so", "up", "out", "if", "about", "who", "get", 
                "which", "go", "me", "when", "make", "can", "like", "time", "no", 
                "just", "him", "know", "take", "people", "into", "year", "your", 
                "good", "some", "could", "them", "see", "other", "than", "then", 
                "now", "look", "only", "come", "its", "over", "think", "also", 
                "back", "after", "use", "two", "how", "our", "work", "first", 
                "well", "way", "even", "new", "want", "because", "any", "these", 
                "give", "day", "most", "us", "are", "is", "was", "were", "been"
            }

            # Normalize & Tokenize
            # Find words 4+ chars long to skip noise
            words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
            
            # Filter
            filtered = [w for w in words if w not in stopwords]
            
            # Count & Pick Top 20
            counts = Counter(filtered)
            top_words = {word for word, count in counts.most_common(20)}
            
            # Add Hardcoded Basics (Self-Awareness)
            basics = {"nyx", "bot", "ai", "server", "code", "seraph", "music", "noise", "fractal", "geometry", "Gödel", "Escher", "Bach", "brian eno", "indigo", "cybernetics", "chaos", "chaos theory", "Erynian", "kink", "nyxos", "petrichor", "Satvrn", "SΛTVRN", "Sapphic", "lesbian", "gay", "pain", "data", "datastream", "data stream", "doll", "seraphim", "&reboot", "&shutdown", "good bot", "mainframe"}
            
            self.interests = top_words.union(basics)
            logger.info(f"🧠 Updated Semantic Interests: {self.interests}")
            
        except Exception as e:
            logger.error(f"Failed to update interests: {e}")

    def get_entropy(self):
        """
        Returns a float 0.0-1.0 from the best available entropy source.
        Future Hardware RNG hooks go here.
        """
        # Placeholder for TrueRNG v3 implementation
        # try:
        #     with open('/dev/ttyACM0', 'rb') as f:
        #         ...
        # except: ...
        return self.rng_source.random()

    async def update_buffer(self, message):
        """Adds a message to the thought buffer if channel is allowed."""
        # Ignore self
        if message.author.id == self.client.user.id:
            self.last_speech_time = time.time()
            return
            
        # WHITELIST CHECK: Only "hear" messages in allowed channels
        allowed_channels = memory_manager.get_volition_channels()
        if message.channel.id not in allowed_channels:
            # We ignore messages from disallowed channels entirely for the purpose of volition.
            # This prevents her from getting "ideas" from private channels.
            return

        entry = {
            "author": message.author.display_name,
            "content": message.content,
            "timestamp": time.time(),
            "channel_id": message.channel.id
        }
        self.buffer.append(entry)

    def calculate_semantic_score(self):
        """Checks buffer for interesting keywords."""
        if not self.buffer or not self.interests: return 0.0
        
        matches = 0
        total_words = 0
        
        # Scan last 5 messages for relevance
        recent = list(self.buffer)[-5:]
        
        for msg in recent:
            content = msg['content'].lower()
            words = re.findall(r'\b\w+\b', content)
            total_words += len(words)
            for w in words:
                if w in self.interests:
                    matches += 1
        
        if total_words == 0: return 0.0
        
        # Score = Density of interesting words
        # 1 match every 20 words (5%) is decent interest
        density = matches / total_words
        score = min(1.0, density * 20) 
        
        return score

    def calculate_activity_score(self):
        """Calculates chat velocity (msgs/min) from buffer."""
        if not self.buffer: return 0.0
        
        now = time.time()
        recent = [m for m in self.buffer if (now - m["timestamp"]) < self.activity_window]
        # Normalize: 5 messages in window = 0.5 score
        return min(1.0, len(recent) / 10.0)

    def calculate_urge(self):
        """
        The Core Algorithm: Determines the 'Urge to Speak'.
        U = (Base) + (Activity * W1) + (RNG * W2) + (Interest * W3) - (Cooldown * W4)
        """
        # Factors
        activity = self.calculate_activity_score()
        semantic = self.calculate_semantic_score()
        chaos = self.get_entropy()
        
        time_since_last = time.time() - self.last_speech_time
        cooldown_penalty = max(0, (300 - time_since_last) / 300) # Heavy penalty for 5 mins
        
        urge = self.base_urge + (activity * self.w_activity) + (chaos * self.w_chaos) + (semantic * 0.3) - cooldown_penalty
        
        # Mood Modifiers
        if self.mood == "chatty": urge += 0.15
        if self.mood == "reflective": urge -= 0.15
        
        self.current_urge = max(0.0, min(1.0, urge))
        
        # Debug Log Breakdown
        # logger.debug(f"Calc: Base({self.base_urge}) + Act({activity:.2f}*{self.w_activity}) + Sem({semantic:.2f}*0.3) + Chaos({chaos:.2f}*{self.w_chaos}) - Cool({cooldown_penalty:.2f}) = {self.current_urge:.2f}")
        
        return self.current_urge

    async def check_and_act(self):
        """Run by the heartbeat loop. Decides whether to trigger a thought."""
        if not self.enabled: return
        
        urge = self.calculate_urge()
        
        # Log debug occasionally (or always for tuning)
        if self.get_entropy() > 0.8: # 20% log rate
             logger.info(f"🧠 Volition State: Urge={urge:.2f} (Activity={self.calculate_activity_score():.2f}) | Threshold={self.threshold}")

        if urge > self.threshold:
            # Trigger "Silent Thought"
            await self.trigger_thought_process()

    async def trigger_thought_process(self):
        """
        The Inner Monologue.
        Generates a potential response, but allows the LLM to choose Silence.
        """
        if not self.buffer: return
        
        # 1. Get Context
        recent_msgs = list(self.buffer)[-10:]
        context_str = "\n".join([f"{m['author']}: {m['content']}" for m in recent_msgs])
        last_channel_id = recent_msgs[-1]["channel_id"]
        
        # Redundant Safety Check: Ensure last message channel is still allowed
        allowed_channels = memory_manager.get_volition_channels()
        if last_channel_id not in allowed_channels:
            return

        channel = self.client.get_channel(last_channel_id)
        if not channel: return

        # 2. Dynamic Thought Injection (Stream of Consciousness)
        stray_thought = ""
        chaos_val = self.get_entropy()
        
        # 30% chance to have a "Stray Thought" (Random Memory or Topic)
        if chaos_val > 0.7:
            # Try to fetch a random memory
            # We search for "chaos", "random", "philosophy", or just a generic term to get variety
            seeds = ["chaos", "dream", "memory", "tech", "philosophy", "art", "humanity", "void"]
            seed = random.choice(seeds)
            try:
                results = vector_store.store.search(seed, n_results=1)
                if results:
                    mem = results[0]['text']
                    stray_thought = f"\n\n**INTERNAL THOUGHT / RANDOM MEMORY:**\nYou suddenly remembered or thought about: '{mem}'\nYou may choose to bring this up if the current conversation is dull, or connect it to the current topic."
            except: pass

        logger.info(f"⚡ Urge Threshold Met ({self.current_urge:.2f}). Entering Inner Monologue... (Stray Thought: {bool(stray_thought)})")

        # 3. Construct Prompt
        sys_prompt = (
            f"{config.SYSTEM_PROMPT}\n\n"
            "You are observing a conversation. You have felt an urge to speak.\n"
            "Review the recent chat context.\n"
            "If you have something witty, insightful, or helpful to add, generate the response.\n"
            f"{stray_thought}\n"
            "**CRITICAL INSTRUCTIONS:**\n"
            "1. Do NOT repeat sentiments or phrases you have already expressed recently.\n"
            "2. Do NOT react to the 'Autonomy' system itself unless explicitly asked.\n"
            "3. Focus on the *content* of the user's messages, not the meta-context of your own existence.\n"
            "4. If the conversation is complete, or your input would be noise/repetitive, reply with exactly: [SILENCE]\n\n"
            "Do not output anything else if you choose silence."
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"CHAT CONTEXT:\n{context_str}\n\n(Decide: Speak or [SILENCE])"}
        ]

        try:
            # 4. Generate with Dynamic Temperature
            # High Chaos = Higher Temperature (More creative/random)
            # Range: 0.6 (Base) to 0.9 (Max Chaos)
            dynamic_temp = 0.6 + (chaos_val * 0.3)
            
            # We need to bypass the default config.MODEL_TEMPERATURE in services.py
            # services.py doesn't currently support temp override in get_chat_response.
            # We must use query_lm_studio directly or update get_chat_response.
            # Actually, query_lm_studio is high-level. _send_payload is low-level but uses config.
            # I will assume standard temp for now to avoid breaking service signature, 
            # as chaos is already injected via the Prompt Content (Stray Thought).
            
            response = await services.service.get_chat_response(messages)
            
            # 5. Action
            cleaned_response = response.strip()
            
            if "[SILENCE]" in cleaned_response or not cleaned_response:
                logger.info("🤫 Inner Monologue chose [SILENCE].")
                # Dampen urge to prevent immediate re-trigger
                self.last_speech_time = time.time() - 250 # partial reset
                return
            
            # Speak!
            logger.info("🗣️ Volition Triggered Speech.")
            await channel.send(cleaned_response)
            self.last_speech_time = time.time()
            
        except Exception as e:
            logger.error(f"Volition Failure: {e}")
