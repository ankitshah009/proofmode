"""ASGI entry point for hosted deployments (for example Vercel).

Local use: `uv run python -m proofmode`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from proofmode.app import create_app

app = create_app()
