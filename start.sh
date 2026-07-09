#!/bin/bash
echo "BIST Bot baslatiliyor..."
cd "$(dirname "$0")"

# Mac'lerde genelde python3 yukludur veya venv (sanal ortam) kullanilir
if [ -d "venv" ]; then
    ./venv/bin/python run_bot.py
elif command -v python3 &>/dev/null; then
    python3 run_bot.py
else
    python run_bot.py
fi
