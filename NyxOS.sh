#!/bin/bash
cd "$(dirname "$0")"

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

# Kill other instances of this script
my_pid=$$
other_scripts=$(pgrep -f "NyxOS.sh" | grep -v "$my_pid")
if [ -n "$other_scripts" ]; then
    echo "🔪 Killing stuck script instances: $other_scripts"
    kill -9 $other_scripts 2>/dev/null || true
fi

pkill -9 -f "python.*NyxOS.py" || true
sleep 1

# 5. Launch Bot
echo "🚀 Starting NyxOS..."
python3 NyxOS.py

