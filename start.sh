#!/bin/bash
set -e

echo ""
echo "=========================================="
echo "  MOZA RACING US Price Monitor"
echo "  Starting Backend Server..."
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 not found. Install Python 3.10+ first."
    exit 1
fi

cd "$BACKEND_DIR"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "[INFO] Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "[INFO] Starting server on http://127.0.0.1:5000"
echo "[INFO] Press Ctrl+C to stop."
echo ""

# 自动打开浏览器
(sleep 2 && (open http://127.0.0.1:5000 || xdg-open http://127.0.0.1:5000)) &

python app.py
