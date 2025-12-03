#!/bin/bash
cd "$(dirname "$0")"

# Trap Ctrl+C
trap "echo '🛑 Manual interrupt detected. Exiting wrapper.'; exit 0" SIGINT SIGTERM

# 1. Auto-Setup Virtual Environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Activate Environment
source venv/bin/activate

# 3. Install/Update Dependencies
echo "📥 Checking dependencies..."
pip install -r requirements.txt --quiet

# 4. Launch Daemon
echo "👻 Starting NyxOS Daemon..."
# The Daemon handles process cleanup, crash detection, and restarts.
python3 NyxOSDaemon.py
