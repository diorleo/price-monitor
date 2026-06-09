"""
wsgi.py — WSGI entry point for Railway/gunicorn
"""
import sys
import os

# Add backend to Python path so imports work from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app import app

if __name__ == '__main__':
    app.run()
