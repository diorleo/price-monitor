"""
wsgi.py — Entry point for Railway / gunicorn / Flask dev server
 gunicorn wsgi:app   ← Railway / Procfile
 python wsgi.py    ← direct run
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

from app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask on port {port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
