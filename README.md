<img width="514" height="238" alt="image" src="https://github.com/user-attachments/assets/2a2f06c3-f028-4f35-bd17-f9c81b5301be" />

# 🌙 NyxOS v2.0

This is an experimental personal project for running an LLM on local hardware via LM Studio, which integrates it with Discord. 

It works natively on Linux right now. If you want to run it on Windows, you can run it through Windows Subsystem for Linux (WSL).

<img width="601" height="336" alt="image" src="https://github.com/user-attachments/assets/5a2dcebd-f399-4e31-830d-4f80f6c86723" />

## ✨ Features

### 🧠 Core Intelligence
*   **Local LLM Brain**:  She talks via LM Studio running on your own hardware. No cloud fees, total privacy.
*   **Vision Support**:  She can see images you attach! 🖼️
*   **Smart Web Search**:  Powered by Kagi. She autonomously Googles things if she needs facts, or you can force it with `&web`.
*   **Context-Aware**:  Keeps track of conversations per-channel. Memories auto-fade after 8 hours of silence (or you can wipe them manually).

### 📡 The "Uplink Bar"
A persistent, stylized status bar that hangs out at the bottom of the chat.
*   **Live Status**:  Shows what she's doing (Thinking, Reading, Sleeping, Watching).
*   **Checkmark System**:  Leaves a little "All Caught Up" checkmark behind so you know where you left off.
*   **Auto-Drop**:  The bar automatically moves down when she replies, keeping the chat clean.
*   **Sleep Mode**:  Put all bars to sleep with `/sleep` when you're done for the day.

### 🧩 Integration
*   **PluralKit Native**:  Fully system-aware! She recognizes proxies, resolves them to the real system owner, and handles "Good Bot" points correctly.
*   **Embed Nuke**:  Hate link previews clogging the chat? `/killmyembeds` auto-suppresses them for you (or globally for the server).

### 🛠️ Admin & Reliability
*   **Channel Whitelist**:  She only speaks where allowed (unless you enable Global Mode).
*   **Debug Suite**:  Built-in tools to run unit tests, wipe logs, or reboot the process right from Discord.
*   **Robustness**:  Auto-restarts on crashes, handles shutdowns gracefully, and sanitizes inputs to keep the LLM from getting confused.
*   **Smart Sync**:  Slash commands only sync when the code actually changes to save API calls.

### 🎮 Fun Stuff
*   **Good Bot Leaderboard**:  Track who pets the bot the most with `/goodbot`.
*   **Infinite Regen**:  Don't like a reply? Hit retry forever (with a tiny cooldown).
*   **Bug Reports**:  Submit issues directly through a Discord modal form.

## ⚡ Quick Start

### 1. Clone & Enter
```bash
git clone https://github.com/seraphimoftines/nyxos.git
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
(Most work with both Slash `/` and Prefix `&`)

**General**
| Command | Description |
| :--- | :--- |
| `&help` | Show the full command list. |
| `&killmyembeds` | Toggle link preview suppression for yourself. |
| `&goodbot` | Check the leaderboard. |
| `&web <query>` | Force a web search. |
| `/reportbug` | Submit a bug report via form. |

**Uplink Bar**
| Command | Description |
| :--- | :--- |
| `/bar <text>` | Spawn a new status bar in the current channel. |
| `/drop` | Force the bar to move to the bottom. |
| `/sleep` | Put all bars to sleep (inactive). |
| `/wake` | Wake up all bars in allowed channels. |
| `/idle` | Set all bars to "Not Watching". |
| `&global <text>` | Update the text on ALL active bars instantly. |

**Admin**
| Command | Description |
| :--- | :--- |
| `&addchannel` | Whitelist current channel. |
| `&removechannel` | Blacklist current channel. |
| `&clearmemory` | Wipe current channel memory. |
| `&suppressembedson` | Enable server-wide embed suppression. |
| `&debug` | Toggle debug mode (unlocks buttons: Reboot, Shutdown, Test, Wipe). |
| `/debugtest` | Run the internal unit test suite. |

## 🐛 Bugs
Still lots of them! But fewer than before.

## 🌐 Links
I'm an artist, musician, and streamer!
- Twitch: https://broadcast.HyperSystem.xyz
- Community: https://temple.HyperSystem.xyz
- My Music: https://music.HyperSystem.xyz (Free!)
- Bluesky: https://bsky.app/profile/goddesscalyptra.com
