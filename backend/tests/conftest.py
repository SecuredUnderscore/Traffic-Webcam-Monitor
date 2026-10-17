import os
from pathlib import Path

# Must run before any test module imports app.*, which reads these at import time.
os.environ.setdefault("TW_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "models"))
