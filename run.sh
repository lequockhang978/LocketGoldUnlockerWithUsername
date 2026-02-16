#!/bin/bash
cd "$(dirname "$0")"

# Check & Create Virtual Environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install python-telegram-bot requests aiohttp
fi

echo "🚀 Starting Locket Gold V2 (Professional Edition)..."

# Kill existing instances
pkill -f "python3 bot.py" 2>/dev/null
pkill -f "main.py" 2>/dev/null
sleep 1

# Run Main
./venv/bin/python3 main.py
