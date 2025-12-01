import asyncio
import time
import logging
import inspect
from collections import defaultdict

logger = logging.getLogger("RateLimiter")

class RateLimiter:
    def __init__(self):
        # Buckets: key -> list of timestamps
        self.buckets = defaultdict(list)
        self.locks = defaultdict(asyncio.Lock)
        
        # Limits: (count, seconds)
        # "Leave 1 slot open" logic will be applied dynamically
        self.limits = {
            "send_message": (5, 5),      # Per Channel
            "delete_message": (5, 1),    # Per Channel
            "add_reaction": (1, 0.25),   # Per Channel (Burst)
            "edit_message": (5, 5),      # Per Channel
            "direct_message": (5, 5),    # Per DM Channel
            "update_presence": (5, 60),  # Per Global/Shard
            "identify": (1, 5),          # Per Session
            "channel_rename": (2, 600),  # Very Strict (10 mins)
            "create_role": (250, 172800),# Per Guild (48 hours)
            "global": (45, 1)            # Safety net (Discord is 50/s)
        }

    async def wait_for_slot(self, action, key):
        """
        Waits until a slot is available for the given action and key (e.g. channel_id).
        Automatically enforces the Global Rate Limit for all non-global actions.
        """
        if action not in self.limits:
            return

        # 1. Enforce Global Limit first (if not checking global itself)
        if action != "global":
            await self._wait_for_bucket("global", "all")

        # 2. Enforce Specific Limit
        await self._wait_for_bucket(action, key)

    async def _wait_for_bucket(self, action, key):
        limit, window = self.limits[action]
        
        # "Leave 1 slot open" -> effective limit is limit - 1, unless limit is small
        effective_limit = limit - 1 if limit > 1 else limit

        lock_key = f"{action}:{key}"
        
        async with self.locks[lock_key]:
            now = time.time()
            # 1. Clean old timestamps
            self.buckets[lock_key] = [t for t in self.buckets[lock_key] if now - t < window]
            
            # 2. Check count
            while len(self.buckets[lock_key]) >= effective_limit:
                # Calculate wait time
                oldest = self.buckets[lock_key][0]
                # How long until the oldest one expires?
                # Expires at: oldest + window
                # Wait: (oldest + window) - now
                wait_time = (oldest + window) - now + 0.05 # Small buffer
                
                if wait_time > 0:
                    try:
                        # Stack: [0]=_wait_for_bucket, [1]=wait_for_slot, [2]=Caller
                        frame = inspect.stack()[2]
                        caller_info = f"{frame.filename.split('/')[-1]}:{frame.lineno}"
                    except Exception:
                        caller_info = "Unknown"
                    
                    logger.warning(f"Rate Limit Reached for {action} on {key}. Sleeping {wait_time:.2f}s. Source: {caller_info}")
                    await asyncio.sleep(wait_time)
                
                # Re-check time after sleep
                now = time.time()
                self.buckets[lock_key] = [t for t in self.buckets[lock_key] if now - t < window]

            # 3. Add new timestamp
            self.buckets[lock_key].append(time.time())

    async def manual_add(self, action, key):
        """Manually increment the counter (e.g. for external events). Thread-safe."""
        if action not in self.limits:
            return

        limit, window = self.limits[action]
        lock_key = f"{action}:{key}"
        
        async with self.locks[lock_key]:
             self.buckets[lock_key].append(time.time())

# Global Instance
limiter = RateLimiter()
