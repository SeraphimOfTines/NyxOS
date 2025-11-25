<img width="514" height="238" alt="image" src="https://github.com/user-attachments/assets/2a2f06c3-f028-4f35-bd17-f9c81b5301be" />

# 🌙 NyxOS v2.0

This is an experimental personal project for running an LLM on local hardware via LM Studio, which integrates it with Discord. 

It works natively on Linux right now. If you want to run it on Windows, you can run it through Windows Subsystem for Linux (WSL).

<img width="601" height="336" alt="image" src="https://github.com/user-attachments/assets/5a2dcebd-f399-4e31-830d-4f80f6c86723" />

## ✨ Features

### 🧠 Core Intelligence
*   **Full LLM Integration**: Talks via local hardware using LM Studio.
*   **Vision-Language Support**: Can see images attached in Discord and recall images sent earlier.
*   **Web Search**: Browse the web using Kagi. She generates her own search queries. (Use `&web` to force a search).

### 🧩 Integration & Memory
*   **PluralKit Integration**: System-aware! Waits for proxies to resolve and correctly attributes "Good Bot" points to the system owner.
*   **Persistent Memory**:
    *   Rolling context window.
    *   Per-channel memory.
    *   **Auto-Flush**: Clears memory after 8 hours of inactivity.
    *   Manual flush command available.

### 🎨 Interactive UI
*   **Regenerate**: Infinite retries with a 5s cooldown.
*   **Good Bot**: Tracks score on a leaderboard with anti-spam protection.
*   **Bug Reports**: Dedicated form for bug tracking.

### 🛠️ Server Administration
*   **Embed Suppression**: Toggle `&killmyembeds` to auto-nuke link previews. Admins can toggle this server-wide.
*   **Channel Whitelist**: Restrict bot activity to specific channels.
*   **Smart Sync**: Slash commands only sync on code changes to avoid API rate limits.
*   **Debug Suite**: Admin-only mode unlocking tools like Test Message, Wipe Logs/Memory, Reboot, and Shutdown.

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
The helper script handles the virtual environment and dependencies automatically.
```bash
chmod +x NyxOS.sh
./NyxOS.sh
```

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

| Admin Commands | Description |
| :--- | :--- |
| `&addchannel` | Whitelist current channel. |
| `&removechannel` | Blacklist current channel. |
| `&clearmemory` | Wipe current channel memory. |
| `&suppressembedson` | Enable server-wide embed suppression. |
| `&suppressembedsoff` | Disable server-wide embed suppression. |
| `&debug` | Toggle debug mode (unlocks admin UI buttons). |
| `&reboot` | Restart bot process. |
| `&shutdown` | Gracefully shutdown. |

## 🐛 Bugs
Still lots of them! But fewer than before.

## 🌐 Links
I'm an artist, musician, and streamer!
- Twitch: https://broadcast.HyperSystem.xyz
- Community: https://temple.HyperSystem.xyz
- My Music: https://music.HyperSystem.xyz (Free!)
- Bluesky: https://bsky.app/profile/goddesscalyptra.com
