#!/bin/bash
# MaSoVa Agent - Start Interactive Chat
# Usage: ./scripts/start-chat.sh

cd "$(dirname "$0")/../src/masova_agent"

echo "💬 Starting MaSoVa Interactive Chat..."
echo ""

# Activate virtual environment if not already active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "📦 Activating virtual environment..."
    source ../../.venv/bin/activate
elif [[ "$VIRTUAL_ENV" != "$(cd ../..; pwd)/.venv" ]]; then
    echo "⚠️  Different venv active. Switching to project venv..."
    deactivate
    source ../../.venv/bin/activate
else
    echo "✅ Virtual environment already active"
fi

# Run chat interface
python3 chat.py
