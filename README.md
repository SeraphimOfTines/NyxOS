# NyxOS
This is an experimental personal project for running an LLM on local hardware via LM Studio, which integrates it with Discord.

It works natively on Linux right now. If you want to run it on Windows, you can run it through Windows Subsystem for Linux (WSL)

# Features
- Supports Vision-Language models.
- Has buttons for functions in-chat via Discord bot interactions.
- Web Search: Searches with Kagi; generates its own search queries. Note: Kagi API is in beta and you have to email them for access. (Use !web)
- Prompt regeneration.
- Delete output.
- Bug reports, which send to a specific channel and opens a thread. Uses a form.
- Full working memory with a rolling context window. (Default is 40 messages)
- Per-channel memory.
- Per-channel logging.
- Backlogs contents of channel.
- Flush memory. When this is done the memory stays cleared instead of regenerating.
- She clears her memory per channel when 8 hour timeout has been reached to simulate a break from chat.
- Full logging with timestamps
- System prompt support
- Extra system prompt injection.
- Good bot! You can tell her she's a good bot, and she'll keep track of the score. Includes anti-spam and a leaderboard. Includes anti-spam.
- Discord slash commands.
- Can reload the bot from Discord UI.
- Whitelist for channels that the bot is active in to prevent spam.
- Integration with PluralKit. Waits for the proxy message before replying, and looks up system member info when replying, injecting it into the system prompt as-needed.
- Multimodal support, can see images attached on Discord, and images sent earlier.
- Activates only when pinged or replied to (for now.)
- Automatically converts image formats to formats accepted by LM Studio (Supports converting .webp)
- Scans and sees images previously sent in chat.

# Installation
Clone the repository

Create config.txt, and put the following in it:

```
MY_SYSTEM_ID = ""
BOT_NAME = "NyxOS"
CONTEXT_WINDOW = 40 

# List of Bot Role IDs to listen for
BOT_ROLE_IDS = [
    
]

# Hardcoded Identity Maps
SERAPH_IDS = {
    
}
CHIARA_IDS = {
    
}
# TODO: Set this to your desired startup channel ID.
STARTUP_CHANNEL_ID = 
BUG_REPORT_CHANNEL_ID = 
LM_STUDIO_URL = "http://IP:PORT/v1/chat/completions"
```

- If you use PluralKit, change "MY_SYSTEM_ID" to your system ID. You can find this on the [PluralKit Dashboard](https://dash.pluralkit.me/).
- Adjust "CONTEXT_WINDOW" if you want to change how many messages are stored in her memory. (Default is 40, but 20 is recommended)
- Change "BOT_ROLE_IDS" to the user ID of your bot. You can right click and select "Copy ID" in Discord to find it.
- Leave "SERAPH_IDS" blank.
- Change "CHIARA_IDS" to your user ID. This allows you to admin the bot.
- Edit system_prompt.txt to edit the system prompt.
- Edit injected_prompt.txt to insert the contents into the end of the system prompt
- Paste your Discord Bot token into token.txt
- Paste your Kagi search API token in kagi_token.txt
- Change "STARTUP_CHANNEL_ID" to the channel where you'd like her to post when she starts up.
- Change "BUG_REPORT_CHANNEL_ID" to where you want bug reports to go.
- Change "LM_STUDIO_URL" to the IP and port that LM Studio is running on. You can find this in the LM Studio developer tab. Example: `LM_STUDIO_URL = "http://192.168.0.200:2378/v1/chat/completions"`
- Open LM Studio on your host machine. Choose your server port, and enable CORS. If you want to run the model locally, select "Serve on Local Network." If you're running on a separate server, remember to port forward your router.

# Run her

Run the following in your terminal. Replace /your/directory/here appropriately.

```
# Change Directory
cd '/your/directory/here'

# Update packages (optional but recommended)
sudo apt-get update

# Install Python and pip if you don't have them
sudo apt-get install -y python3 python3-pip

# Activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install discord.py
pip install "discord.py>=2.3.0"

# Run your bot
python3 'NyxOS.py'
```
# Usage
@ping or reply to your bot to make her talk to you!
Send her images in Discord and she will see them! She can see previously sent images too.
Ping her and say "good bot" to add +1 to her good bot counter.

## Commands
```
/addchannel adds a channel to the whitelist so she can talk there.
/removechannel removes channel from the whitelist, and she won't talk there.
/goodbot tells her she's doing a good job, and adds +1 to the good bot counter.
/reload will reload the configuration files. This doesn't reload the python script itself though.
/reportbug reports a bug
/clearmemory resets her memory to blank, which helps clear corruption.
```

# Bugs
Lots of them!

# Links
I'm an artist, and I make music, stream on Twitch, and have a very friendly community! If you'd like to see my art, you can find me here!
- https://temple.HyperSystem.xyz
- https://music.HyperSystem.xyz (Free!)
- https://broadcast.HyperSystem.xyz