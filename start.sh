#!/bin/bash
# Auto-NguLo — Start Script (Termux optimized)
# Run this from the project root directory

echo "🤖 Starting Auto-NguLo..."

# ---- Wake Lock (prevent Android CPU sleep) ----
if command -v termux-wake-lock &>/dev/null; then
    termux-wake-lock 2>/dev/null
    echo "🔒 Wake lock acquired"
fi

# ---- Kill any existing server on port 8000 ----
fuser -k 8000/tcp 2>/dev/null
pkill -9 -f "uvicorn main:app" 2>/dev/null
sleep 1

# ---- Ensure venv exists ----
if [ ! -f "./venv/bin/uvicorn" ]; then
    echo "❌ Virtualenv not found! Run: python -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo ""

# ---- Start FastAPI with nohup (survives terminal close) ----
cd "$(dirname "$0")"
nohup ./venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info \
    --no-access-log \
    > data/server.log 2>&1 &

PID=$!
echo "✅ Server PID: $PID"
echo "📋 Logs: data/server.log"
echo "🌐 http://localhost:8000"
echo ""
echo "💡 Tips biar tetap aktif:"
echo "   - Matikan battery optimization untuk Termux"
echo "   - Gunakan 'termux-wake-lock' manual jika perlu"
echo "   - Cek log: tail -f data/server.log"