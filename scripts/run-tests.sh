#!/bin/bash
# MaSoVa Agent - Run Test Scenarios
# Usage: ./scripts/run-tests.sh

cd "$(dirname "$0")/../tests"

echo "🧪 Running MaSoVa Agent Test Scenarios..."
echo ""

# Activate virtual environment if not already active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "📦 Activating virtual environment..."
    source ../.venv/bin/activate
elif [[ "$VIRTUAL_ENV" != "$(cd ..; pwd)/.venv" ]]; then
    echo "⚠️  Different venv active. Switching to project venv..."
    deactivate
    source ../.venv/bin/activate
else
    echo "✅ Virtual environment already active"
fi

# Run tests
python3 test_scenarios.py
