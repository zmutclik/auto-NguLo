#!/bin/bash
# Auto-NguLo — Start Script
# Run this from the project root directory

echo "🤖 Starting Auto-NguLo..."

# Kill any existing server on port 8000 (both fuser and pkill for reliability)
fuser -k 8000/tcp 2>/dev/null
pkill -9 -f "uvicorn main:app" 2>/dev/null
sleep 1

echo ""

# Start FastAPI server
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-dir ./ --log-level info