#!/bin/bash
# MaSoVa Agent - Start ADK Web Interface
# Usage: ./scripts/start-web.sh

cd "$(dirname "$0")/.."

echo "🚀 Starting MaSoVa Agent Web Interface..."
echo ""

# Activate virtual environment if not already active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "📦 Activating virtual environment..."
    source .venv/bin/activate
elif [[ "$VIRTUAL_ENV" != "$(pwd)/.venv" ]]; then
    echo "⚠️  Different venv active. Switching to project venv..."
    deactivate
    source .venv/bin/activate
else
    echo "✅ Virtual environment already active"
fi

# Start ADK web server
echo "🌐 Launching ADK Web Server..."
echo "   Access at: http://127.0.0.1:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Point to src/ directory for ADK
adk web src

# Note: Server runs from project root
# ADK discovers agents in src/masova_agent/
