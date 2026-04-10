"""Shared pytest fixtures and path setup."""
import sys
from pathlib import Path

# Ensure `backend/` is on path so `import app.*` works regardless of invocation
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
