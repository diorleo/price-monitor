"""
wsgi.py — Entry point for Railway
"""
import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

print("=== Starting wsgi.py ===", flush=True)
print(f"Python: {sys.version}", flush=True)
print(f"sys.path: {sys.path[:3]}", flush=True)

try:
    from app import app
    print("Flask app imported successfully", flush=True)
except Exception as e:
    print(f"FATAL: Failed to import app: {e}", flush=True)
    traceback.print_exc()
    # Fallback: create a minimal app for debugging
    from flask import Flask
    app = Flask(__name__)
    
    @app.route('/')
    def debug_root():
        return f"DEBUG MODE: Import failed - {e}"
    
    @app.route('/api/dashboard')
    def debug_api():
        return {"error": str(e), "status": "import_failed"}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask on port {port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
