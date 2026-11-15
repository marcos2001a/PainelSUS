import os
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR.parent / "DADOS" / "PA 2025 e 2026"
HOSPITAL_DATA_DIR = Path(os.environ.get("TABWIN_RD_DATA_DIR", PROJECT_DIR.parent / "DADOS" / "RD 2026"))
DATABASE_PATH = PROJECT_DIR / "data" / "producao.sqlite3"
DATABASE_STORAGE_DIR = PROJECT_DIR / "data" / "databases"
DATABASE_SELECTION_FILE = PROJECT_DIR / "data" / "selected_database.txt"
HOSPITAL_UPLOAD_DIR = PROJECT_DIR / "data" / "hospital_uploads"

REFERENCE_DIR = Path(os.environ.get("TABWIN_REFERENCE_DIR", PROJECT_DIR.parent))
TEMP_DIR = Path(os.environ.get("TABWIN_TEMP_DIR", tempfile.gettempdir()))
CNES_FILE = PROJECT_DIR / "CNES_TAUBATE.txt"
HOSPITAL_CNES_FILE = PROJECT_DIR / "CNES_TAUBATE_HOSPITALAR.txt"
