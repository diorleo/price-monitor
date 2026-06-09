"""
run.py — Glitch entry point
Glitch auto-detects this as the Python entry
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

# Glitch sets PORT env var
port = int(os.environ.get('PORT', 3000))

from app import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port, debug=False)
