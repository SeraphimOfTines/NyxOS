import discord
import asyncio
import subprocess
import sys
import os
import signal
import time
import logging
import traceback

# Local Modules
import config
import ui
import helpers

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [DAEMON] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("NyxOSDaemon")

class NyxDaemon(discord.Client):
    def __init__(self, crash_context=None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.should_launch = False
        self.crash_context = crash_context  # "CRASH" or "SHUTDOWN"

    async def on_ready(self):
        logger.info(f"👻 Daemon logged in as {self.user} (Standby Mode)")
        
        status_text = "Standby - Waiting for &boot"
        if self.crash_context == "CRASH":
            status_text = "⚠️ SYSTEM CRASHED - Waiting for &boot"
        
        await self.change_presence(activity=discord.Game(name=status_text), status=discord.Status.idle)
        
        # Handle Notifications
        channel = self.get_channel(config.STARTUP_CHANNEL_ID)
        if channel:
            if self.crash_context == "CRASH":
                # Fetch crash message from UI flavor text or fallback
                crash_msg = ui.FLAVOR_TEXT.get("CRASH_MESSAGE", "⚠️ **SYSTEM FAILURE**\nSystem crashed unexpectedly.")
                # Format as subscript per user request
                formatted_msg = f"-# {crash_msg}"
                await channel.send(formatted_msg)
            
            elif self.crash_context == "SHUTDOWN":
                # Optionally confirm we are in standby
                # await channel.send("💤 **System Halted.** Daemon in standby.")
                pass

    async def on_message(self, message):
        # Ignore self
        if message.author.id == self.user.id:
            return

        # Wake Command
        if message.content.strip() == "&boot":
            if helpers.is_authorized(message.author):
                await message.channel.send("⚡ **Boot sequence initiated.**")
                self.should_launch = True
                await self.close()
            else:
                await message.channel.send(ui.FLAVOR_TEXT["NOT_AUTHORIZED"])

def kill_existing_nyx():
    """Kills any running instances of NyxOS.py to prevent duplicates."""
    try:
        # Kill matching processes (exclude self/daemon by targeting exact script name if possible, 
        # but NyxOS.py is distinct from NyxOSDaemon.py)
        logger.info("🧹 Cleaning up old processes...")
        subprocess.run(["pkill", "-9", "-f", "python.*NyxOS.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

def run_bot_process():
    """Launches the main bot process and waits for it to finish."""
    logger.info("🚀 Launching NyxOS.py...")
    
    # Use sys.executable to ensure we use the same python interpreter (venv)
    try:
        process = subprocess.Popen([sys.executable, "NyxOS.py"])
        process.wait()
        return process.returncode
    except Exception as e:
        logger.error(f"Failed to launch subprocess: {e}")
        return 1 # Treat as crash

def main():
    # Initial cleanup on daemon start
    kill_existing_nyx()
    
    crash_count = 0
    MAX_CRASHES = 3

    # Flag to track if we are in a restart loop
    while True:
        start_time = time.time()
        
        # 1. Run the Bot
        exit_code = run_bot_process()
        
        run_duration = time.time() - start_time
        logger.info(f"Process exited with code {exit_code} (Ran for {run_duration:.2f}s)")

        # Reset crash count if bot was stable for > 60 seconds
        if run_duration > 60:
            crash_count = 0

        # 2. Check for Shutdown Flag (Graceful Shutdown)
        shutdown_requested = False
        if os.path.exists(config.SHUTDOWN_FLAG_FILE):
            logger.info("🛑 Shutdown flag detected.")
            shutdown_requested = True
            crash_count = 0 # Reset on manual shutdown
            try: os.remove(config.SHUTDOWN_FLAG_FILE)
            except: pass

        # 3. Determine Next State
        if shutdown_requested:
            # CASE: Graceful Shutdown -> Enter Standby
            logger.info("💤 Entering Standby Mode...")
            daemon = NyxDaemon(crash_context="SHUTDOWN")
            daemon.run(config.BOT_TOKEN)
            
            if daemon.should_launch:
                logger.info("⚡ Wake up signal received!")
                crash_count = 0
                continue # Restart Loop
            else:
                logger.info("Daemon exiting.")
                break # Exit Daemon

        elif exit_code != 0:
            # CASE: Crash
            crash_count += 1
            logger.warning(f"⚠️ Crash detected! (Count: {crash_count}/{MAX_CRASHES})")
            
            if crash_count < MAX_CRASHES:
                logger.info("🔄 Attempting auto-restart in 5 seconds...")
                time.sleep(5)
                continue
            else:
                # Too many crashes -> Standby
                logger.error("❌ Too many consecutive crashes. Entering Recovery Mode.")
                daemon = NyxDaemon(crash_context="CRASH")
                daemon.run(config.BOT_TOKEN)
                
                if daemon.should_launch:
                    logger.info("⚡ Wake up signal received!")
                    crash_count = 0
                    continue
                else:
                    break
        
        else:
            # CASE: Exit Code 0 (No Flag) -> Reboot
            # This happens when NyxOS.py restarts itself or just exits cleanly without flag
            logger.info("🔄 Rebooting immediately...")
            time.sleep(1)
            continue

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user.")
        kill_existing_nyx()
