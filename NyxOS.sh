#!/bin/bash
cd "$(dirname "$0")"

# Trap Ctrl+C to exit the loop
trap "echo '🛑 Manual interrupt detected. Exiting watcher.'; exit 0" SIGINT SIGTERM

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

# 4. Cleanup Previous Instances
echo "☢️  Nuking old processes..."

# Kill other instances of this script (careful not to kill self if logic is tricky, but pgrep usually safe)
my_pid=$$
other_scripts=$(pgrep -f "NyxOS.sh" | grep -v "$my_pid")
if [ -n "$other_scripts" ]; then
    echo "🔪 Killing stuck script instances: $other_scripts"
    kill -9 $other_scripts 2>/dev/null || true
fi

pkill -9 -f "python.*NyxOS.py" || true
sleep 7

# 5. Launch Bot Loop
echo "🚀 Starting NyxOS Watcher..."

while true; do
    python3 NyxOS.py
    EXIT_CODE=$?
    
    # Check for explicit shutdown flag (Created by NyxOS.py on /shutdown)
    if [ -f "shutdown.flag" ]; then
        echo "🛑 Shutdown flag detected. Powering down."
        rm "shutdown.flag"
        break
    fi
    
    echo "🔄 Process exited (Code: $EXIT_CODE). Restarting in 8 seconds..."
    sleep 8
done