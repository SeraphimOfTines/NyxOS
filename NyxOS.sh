# Change Directory
cd '/home/nova/NyxOS Discord'

# Update packages (optional but recommended)
sudo apt-get update

# Install Python and pip if you don't have them
sudo apt-get install -y python3 python3-pip

# Optionally create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install discord.py
pip install "discord.py>=2.3.0"

# Run your bot (bot.py is the file containing your script
python3 'NyxOS.py'
