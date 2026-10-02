"""Compatibility entry point: uvicorn main:app --host 127.0.0.1 --port 8000."""
from app.main import create_app
app = create_app()
