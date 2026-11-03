import os
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR.parent / "DADOS" / "PA 2025 e 2026"
DATABASE_PATH = PROJECT_DIR / "data" / "producao.sqlite3"

REFERENCE_DIR = Path(os.environ.get("TABWIN_REFERENCE_DIR", PROJECT_DIR.parent / "TABWIN"))
TEMP_DIR = Path(os.environ.get("TABWIN_TEMP_DIR", tempfile.gettempdir()))
