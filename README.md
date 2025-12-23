<img width="514" height="238" alt="image" src="https://github.com/user-attachments/assets/2a2f06c3-f028-4f35-bd17-f9c81b5301be" />

# 🌙 NyxOS v2.0

This is an experimental personal project for running an LLM on local hardware via LM Studio, which integrates it with Discord. 

It works natively on Linux right now. If you want to run it on Windows, you can run it through Windows Subsystem for Linux (WSL).

<img width="601" height="336" alt="image" src="https://github.com/user-attachments/assets/5a2dcebd-f399-4e31-830d-4f80f6c86723" />

## ✨ Features

### 🧠 Core Intelligence
*   **Full LLM Integration**: Talks via local hardware using LM Studio.
*   **Volition (Proactive Autonomy)**: Nyx has "Free Will". She reads chat (in whitelisted channels) and decides when to speak based on:
    *   **Activity**: Chat velocity/speed.
    *   **Semantics**: Interest in specific topics (extracted from her System Prompt).
    *   **Chaos**: Random internal entropy.
    *   **Stream of Consciousness**: Can spontaneously recall random memories or topics if bored.
*   **Emotional Core**: A simulated emotional engine containing 7 distinct parameters (0-100 scale):
    *   **Stats**: `Joy`, `Sadness`, `Anger`, `Anxiety`, `Boredom`, `Loneliness`, and `Energy`.
    *   **Dynamic Personality**: Emotional states directly inject instructions into the LLM. If she is "Exhausted" (Low Energy), she becomes lethargic and short. If "Furious" (High Anger), she loses patience.
    *   **Interaction Effects**:
        *   **Praise**: Increases `Joy` & `Energy`, reduces negative stats.
        *   **Cruelty/Hate**: drastically increases `Sadness` & `Anger`.
        *   **Threats**: Spikes `Anxiety`.
        *   **Apologies**: Help reduce `Anger`.
    *   **Lifecycle**: Energy drains with interaction and recharges over time. High emotions decay back to neutral.
*   **Vector Memory (RAG)**: Connects to **OpenWebUI's** ChromaDB. She can "read" any documents you upload to your local OpenWebUI instance.
*   **YouTube Literacy**: Automatically fetches and reads transcripts from shared YouTube videos.
*   **Vision-Language Support**: Can see images attached in Discord and recall images sent earlier.
*   **Web Search**: Browse the web using Kagi. She generates her own search queries. (Use `&web` to force a search).

### 🎛️ Control Center
*   **NyxAPI**: A local REST API allowing external control of the bot.
*   **NyxControl (Desktop)**: A Python/Tkinter GUI for drag-and-drop status management and real-time monitoring.
*   **NyxControlWeb**: A modern React/Vite web dashboard for controlling Nyx from any device on your network.

### 🧩 Integration & Memory
*   **PluralKit Integration**: System-aware!
    *   **Local Mirror**: Can mirror your PK database locally for zero-latency lookups.
    *   **Proxy Cache**: Robustly identifies members to prevent double-replies.
*   **Midnight Reflection**: Every night at 00:00, she reflects on the day's conversations and summarizes them into long-term memory.
*   **Persistent Memory**:
    *   Rolling context window.
    *   Per-channel memory.
    *   **Auto-Flush**: Clears memory after 8 hours of inactivity.

### 🎨 Interactive UI
*   **Status Bar 2.0**:
    *   **Touch-to-Adopt**: Click any old/broken status bar to instantly fix and claim it.
    *   **Global Sync**: Update every status bar in every channel instantly.
    *   **Smart Modes**: `/sleep` and `/idle` commands to manage bot presence globally.
*   **Regenerate**: Infinite retries with a 5s cooldown.
*   **Good Bot**: Tracks score on a leaderboard with anti-spam protection.
*   **Bug Reports**: Dedicated form for bug tracking.

### 🛠️ Server Administration
*   **Embed Suppression**: Toggle `&killmyembeds` to auto-nuke link previews. Admins can toggle this server-wide.
*   **Channel Whitelist**: Restrict bot activity to specific channels.
*   **Smart Sync**: Slash commands only sync on code changes to avoid API rate limits.
*   **Debug Suite**: Admin-only mode unlocking tools like Test Message, Wipe Logs/Memory, Reboot, and Shutdown.
*   **Response Whitelist**: Only Admins and Special roles can talk to her!

### 🛡️ Robustness
*   Graceful shutdowns and reboots.
*   Input sanitization to protect LLM memory.
*   Hyperlink reconstruction for valid Discord Markdown.

## ⚡ Quick Start

### 1. Clone & Enter
```bash
git clone https://github.com/yourusername/nyxos.git
cd nyxos
```

### 2. Create Configuration
```bash
cp config_example.txt config.txt
```

### 3. Add Secrets & Settings
Open `config.txt` and fill in:
*   **`BOT_TOKEN`**: Discord Bot Token.
*   **`KAGI_API_TOKEN`** (Optional): Web search capability.
*   **`LM_STUDIO_URL`**: LLM endpoint (e.g., `http://localhost:1234/v1/chat/completions`).
*   **`SERAPH_IDS`**: Admin User IDs.
*   **`STARTUP_CHANNEL_ID`**: Channel for startup/shutdown announcements.

### 4. Customize Persona
Edit `config.txt`:
*   **`SYSTEM_PROMPT`**: Core personality instructions.
*   **`INJECTED_PROMPT`**: Additional context.

### 5. Launch 🚀
The helper scripts handle the virtual environment and dependencies automatically.

**Linux / WSL:**
```bash
chmod +x NyxOS.sh
./NyxOS.sh
```

**Windows:**
```powershell
.\NyxOS.ps1
```

### 6. PluralKit Configuration (Optional)
You can toggle between the public PluralKit API and a local instance in `config.txt`:
*   **`USE_LOCAL_PLURALKIT = False`** (Default): Connects to the public API (`api.pluralkit.me`).
*   **`USE_LOCAL_PLURALKIT = True`**: Connects to a local instance (default: `localhost:5000`).

## 🎮 Usage Guide

Ping (`@NyxOS`) or reply to her to wake her up!

### 🕹️ Commands
(Works with Slash `/` and Prefix `&`)

| User Commands | Description |
| :--- | :--- |
| `&help` | Show command list. |
| `&killmyembeds` | Toggle link preview suppression for you. |
| `&goodbot` | Show the leaderboard. |
| `&web <query>` | Force a web search. |
| `&autonomy status` | Check Volition state (Urge, Mood, Breakdown). |
| `&autonomy enable` | Turn on Free Will (Global). |
| `&autonomy allow_here` | Whitelist current channel for autonomy. |
| `&autonomy mood <type>` | Set mood: `neutral`, `chatty`, or `reflective`. |

| Admin Commands | Description |
| :--- | :--- |
| `&addchannel` | Whitelist current channel (for replies). |
| `&removechannel` | Blacklist current channel (for replies). |
| `&clearmemory` | Wipe current channel memory. |
| `&cleargoodbots` | Wipe the Good Bot leaderboard. |
| `&suppressembedson` | Enable server-wide embed suppression. |
| `&suppressembedsoff` | Disable server-wide embed suppression. |
| `&debug` | Toggle debug mode (unlocks admin UI buttons). |
| `&reboot` | Restart bot process. |
| `&shutdown` | Gracefully shutdown. |
| `&bar`, `&drop`, `&addbar` | Status Bar controls (Uplink). |
| `&sleep`, `&idle`, `&awake` | Set Global Status Bar state. |
| `&global <text>` | Update text on ALL status bars instantly. |

## 🐛 Bugs
Less bugs than usual!

## 🌐 Links
I'm an artist, musician, and streamer!
- Twitch: https://broadcast.HyperSystem.xyz
- Community: https://temple.HyperSystem.xyz
- My Music: https://music.HyperSystem.xyz (Free!)
- Bluesky: https://bsky.app/profile/goddesscalyptra.com
