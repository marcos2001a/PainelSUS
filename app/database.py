import sqlite3
from contextlib import contextmanager
from .config import DATABASE_PATH


@contextmanager
def connect(database_path=DATABASE_PATH):
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def initialize_database(database_path=DATABASE_PATH):
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_files (
                id INTEGER PRIMARY KEY,
                relative_path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                record_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS production (
                source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                cnes TEXT NOT NULL,
                competence TEXT NOT NULL,
                procedure_code TEXT NOT NULL,
                submitted_quantity INTEGER NOT NULL DEFAULT 0,
                approved_quantity INTEGER NOT NULL DEFAULT 0,
                submitted_value_cents INTEGER NOT NULL DEFAULT 0,
                approved_value_cents INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (source_file_id, cnes, competence, procedure_code)
            );
            CREATE TABLE IF NOT EXISTS facilities (
                cnes TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS procedures (
                code TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                source TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_production_cnes_competence
                ON production (cnes, competence);
            CREATE INDEX IF NOT EXISTS idx_production_competence
                ON production (competence);
            CREATE INDEX IF NOT EXISTS idx_production_procedure
                ON production (procedure_code);

            CREATE TABLE IF NOT EXISTS hospital_source_files (
                id INTEGER PRIMARY KEY,
                relative_path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                record_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS hospital_production (
                source_file_id INTEGER NOT NULL REFERENCES hospital_source_files(id) ON DELETE CASCADE,
                cnes TEXT NOT NULL,
                competence TEXT NOT NULL,
                procedure_code TEXT NOT NULL,
                admissions INTEGER NOT NULL DEFAULT 0,
                deaths INTEGER NOT NULL DEFAULT 0,
                length_of_stay_days INTEGER NOT NULL DEFAULT 0,
                total_value_cents INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (source_file_id, cnes, competence, procedure_code)
            );
            CREATE INDEX IF NOT EXISTS idx_hospital_cnes_competence
                ON hospital_production (cnes, competence);
            CREATE INDEX IF NOT EXISTS idx_hospital_competence
                ON hospital_production (competence);
            CREATE INDEX IF NOT EXISTS idx_hospital_procedure
                ON hospital_production (procedure_code);
            """
        )
