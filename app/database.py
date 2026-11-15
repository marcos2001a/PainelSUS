import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import (
    DATABASE_PATH,
    DATABASE_SELECTION_FILE,
    DATABASE_STORAGE_DIR,
)


def active_database_path() -> Path:
    if not DATABASE_SELECTION_FILE.is_file():
        return DATABASE_PATH

    filename = DATABASE_SELECTION_FILE.read_text(encoding="utf-8").strip()
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".sqlite3"):
        raise ValueError("A configuração do banco de dados selecionado é inválida.")

    path = DATABASE_STORAGE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"O banco de dados selecionado não foi encontrado: {path}")
    return path


def select_database(filename: str) -> Path:
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".sqlite3"):
        raise ValueError("Selecione um arquivo .sqlite3 válido.")

    path = DATABASE_STORAGE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de banco de dados não encontrado: {path}")

    DATABASE_SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = DATABASE_SELECTION_FILE.with_suffix(".tmp")
    temporary_path.write_text(filename, encoding="utf-8")
    temporary_path.replace(DATABASE_SELECTION_FILE)
    return path


def prune_unlisted_units(
    ambulatory_cnes: set[str],
    hospital_cnes: set[str],
    database_path: Path | None = None,
) -> dict[str, int]:
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TEMP TABLE allowed_ambulatory_cnes (cnes TEXT PRIMARY KEY)"
        )
        connection.execute(
            "CREATE TEMP TABLE allowed_hospital_cnes (cnes TEXT PRIMARY KEY)"
        )
        connection.execute(
            "CREATE TEMP TABLE allowed_facility_cnes (cnes TEXT PRIMARY KEY)"
        )
        connection.executemany(
            "INSERT INTO allowed_ambulatory_cnes (cnes) VALUES (?)",
            ((cnes,) for cnes in ambulatory_cnes),
        )
        connection.executemany(
            "INSERT INTO allowed_hospital_cnes (cnes) VALUES (?)",
            ((cnes,) for cnes in hospital_cnes),
        )
        connection.executemany(
            "INSERT INTO allowed_facility_cnes (cnes) VALUES (?)",
            ((cnes,) for cnes in ambulatory_cnes | hospital_cnes),
        )
        removed = {
            "ambulatory": connection.execute(
                "DELETE FROM production WHERE cnes NOT IN "
                "(SELECT cnes FROM allowed_ambulatory_cnes)"
            ).rowcount,
            "demographics": connection.execute(
                "DELETE FROM production_demographics WHERE cnes NOT IN "
                "(SELECT cnes FROM allowed_ambulatory_cnes)"
            ).rowcount,
            "hospital": connection.execute(
                "DELETE FROM hospital_production WHERE cnes NOT IN "
                "(SELECT cnes FROM allowed_hospital_cnes)"
            ).rowcount,
            "facilities": connection.execute(
                "DELETE FROM facilities WHERE cnes NOT IN "
                "(SELECT cnes FROM allowed_facility_cnes)"
            ).rowcount,
        }
        connection.commit()
    return removed


@contextmanager
def connect(database_path: Path | None = None):
    database_path = active_database_path() if database_path is None else database_path
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def initialize_database(database_path: Path | None = None):
    database_path = active_database_path() if database_path is None else database_path
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
                demographics_version INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS production_demographics (
                source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
                cnes TEXT NOT NULL,
                competence TEXT NOT NULL,
                procedure_code TEXT NOT NULL,
                age_flag TEXT NOT NULL DEFAULT '',
                age_value TEXT NOT NULL DEFAULT '',
                sex TEXT NOT NULL DEFAULT '',
                race TEXT NOT NULL DEFAULT '',
                cid_primary TEXT NOT NULL DEFAULT '',
                cid_secondary TEXT NOT NULL DEFAULT '',
                cid_associated TEXT NOT NULL DEFAULT '',
                submitted_quantity INTEGER NOT NULL DEFAULT 0,
                approved_quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (
                    source_file_id, cnes, competence, procedure_code, age_flag,
                    age_value, sex, race, cid_primary, cid_secondary, cid_associated
                )
            );
            CREATE INDEX IF NOT EXISTS idx_demographics_cnes_competence
                ON production_demographics (cnes, competence);
            CREATE INDEX IF NOT EXISTS idx_demographics_competence
                ON production_demographics (competence);

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
        for table in ("source_files", "hospital_source_files"):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "cnes_filter_signature" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} "
                    "ADD COLUMN cnes_filter_signature TEXT NOT NULL DEFAULT ''"
                )
        source_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(source_files)")
        }
        if "demographics_version" not in source_columns:
            connection.execute(
                "ALTER TABLE source_files "
                "ADD COLUMN demographics_version INTEGER NOT NULL DEFAULT 0"
            )
