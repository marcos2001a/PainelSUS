"""Importa agregados de internações dos arquivos reduzidos do SIH/SUS."""

import argparse
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

from dbfread import DBF
from pyreaddbc import dbc2dbf

from .config import HOSPITAL_CNES_FILE, HOSPITAL_DATA_DIR, REFERENCE_DIR, TEMP_DIR
from .cnes import cnes_filter_signature, load_cnes_registry
from .database import active_database_path, connect, initialize_database

FILE_PATTERN = re.compile(r"^RDSP\d{4}\.dbc$", re.IGNORECASE)
REQUIRED_FIELDS = {"ANO_CMPT", "MES_CMPT", "CNES", "PROC_REA", "VAL_TOT", "MORTE", "DIAS_PERM"}
CHUNK_SIZE = 50_000
ProgressCallback = Callable[[dict], None]


def discover_files(data_dir: Path = HOSPITAL_DATA_DIR) -> list[Path]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Pasta de dados hospitalares não encontrada: {data_dir}")
    return sorted(
        (path for path in data_dir.iterdir() if path.is_file() and FILE_PATTERN.fullmatch(path.name)),
        key=lambda path: path.name.upper(),
    )


def _integer(value) -> int:
    if value in (None, ""):
        return 0
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _cents(value) -> int:
    if value in (None, ""):
        return 0
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def _flush(connection: sqlite3.Connection, source_id: int, totals: dict) -> int:
    if not totals:
        return 0
    connection.executemany(
        """
        INSERT INTO hospital_production (
            source_file_id, cnes, competence, procedure_code,
            admissions, deaths, length_of_stay_days, total_value_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_file_id, cnes, competence, procedure_code) DO UPDATE SET
            admissions = hospital_production.admissions + excluded.admissions,
            deaths = hospital_production.deaths + excluded.deaths,
            length_of_stay_days = hospital_production.length_of_stay_days + excluded.length_of_stay_days,
            total_value_cents = hospital_production.total_value_cents + excluded.total_value_cents
        """,
        [(source_id, *key, *values) for key, values in totals.items()],
    )
    count = len(totals)
    totals.clear()
    return count


def _import_one(
    path: Path,
    data_dir: Path,
    connection: sqlite3.Connection,
    allowed_cnes: set[str],
    filter_signature: str,
    temp_dir: Path,
) -> dict:
    stat = path.stat()
    relative_path = path.relative_to(data_dir).as_posix()
    previous = connection.execute(
        "SELECT id, size_bytes, modified_ns, cnes_filter_signature "
        "FROM hospital_source_files WHERE relative_path = ?",
        (relative_path,),
    ).fetchone()
    if (
        previous
        and previous["size_bytes"] == stat.st_size
        and previous["modified_ns"] == stat.st_mtime_ns
        and previous["cnes_filter_signature"] == filter_signature
    ):
        return {"file": path.name, "status": "skipped_unchanged"}

    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, dbf_name = tempfile.mkstemp(prefix="tabwin_sih_", suffix=".dbf", dir=temp_dir)
    os.close(fd)
    dbf_path = Path(dbf_name)
    try:
        dbc2dbf(str(path), str(dbf_path))
        table = DBF(
            str(dbf_path), load=False, encoding="cp850",
            char_decode_errors="replace", ignore_missing_memofile=True,
        )
        fields = {field.name.upper() for field in table.fields}
        missing = REQUIRED_FIELDS - fields
        if missing:
            raise ValueError(f"{path.name}: faltam campos necessários: {', '.join(sorted(missing))}")

        connection.execute("BEGIN IMMEDIATE")
        if previous:
            source_id = previous["id"]
            connection.execute("DELETE FROM hospital_production WHERE source_file_id = ?", (source_id,))
        else:
            cursor = connection.execute(
                """INSERT INTO hospital_source_files
                   (relative_path, size_bytes, modified_ns, record_count) VALUES (?, ?, ?, 0)""",
                (relative_path, stat.st_size, stat.st_mtime_ns),
            )
            source_id = cursor.lastrowid

        totals = defaultdict(lambda: [0, 0, 0, 0])
        record_count = skipped_rows = filtered_rows = grouped_rows = 0
        for row in table:
            record_count += 1
            cnes = str(row.get("CNES") or "").strip()
            year = str(row.get("ANO_CMPT") or "").strip()
            month = str(row.get("MES_CMPT") or "").strip().zfill(2)
            procedure = str(row.get("PROC_REA") or "").strip()
            if (
                not re.fullmatch(r"\d{7}", cnes)
                or not re.fullmatch(r"(?:19|20)\d{2}", year)
                or not re.fullmatch(r"0[1-9]|1[0-2]", month)
                or not re.fullmatch(r"\d{1,10}", procedure)
            ):
                skipped_rows += 1
                continue
            if cnes not in allowed_cnes:
                filtered_rows += 1
                continue
            values = totals[(cnes, year + month, procedure)]
            values[0] += 1
            values[1] += 1 if _integer(row.get("MORTE")) else 0
            values[2] += max(0, _integer(row.get("DIAS_PERM")))
            values[3] += _cents(row.get("VAL_TOT"))
            if record_count % CHUNK_SIZE == 0:
                grouped_rows += _flush(connection, source_id, totals)

        grouped_rows += _flush(connection, source_id, totals)
        connection.execute(
            """UPDATE hospital_source_files
               SET size_bytes = ?, modified_ns = ?, record_count = ?,
                   imported_at = CURRENT_TIMESTAMP, cnes_filter_signature = ?
               WHERE id = ?""",
            (stat.st_size, stat.st_mtime_ns, record_count, filter_signature, source_id),
        )
        connection.commit()
        return {
            "file": path.name, "status": "imported", "records": record_count,
            "groups": grouped_rows, "skipped_rows": skipped_rows,
            "filtered_rows": filtered_rows,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        dbf_path.unlink(missing_ok=True)


def _load_references(
    connection: sqlite3.Connection,
    reference_dir: Path,
    allowed_cnes: set[str],
) -> None:
    for path in (reference_dir / "DBF" / "TB_SIGTAW.DBF", reference_dir / "DBF" / "TB_SIGTAW.dbf"):
        if not path.is_file():
            continue
        table = DBF(str(path), load=False, encoding="cp850", char_decode_errors="replace", ignore_missing_memofile=True)
        fields = {field.name.upper() for field in table.fields}
        if {"IP_COD", "IP_DSCR"}.issubset(fields):
            connection.executemany(
                """INSERT INTO procedures (code, description, source) VALUES (?, ?, ?)
                   ON CONFLICT (code) DO UPDATE SET description = excluded.description, source = excluded.source""",
                (
                    (code, description, path.name)
                    for row in table
                    if (code := str(row.get("IP_COD") or "").strip())
                    and (description := str(row.get("IP_DSCR") or "").strip())
                ),
            )
        break

    # A hospital CNES can exist in SIH even when it has no PA production.
    for path in (reference_dir / "DBF" / "TCNESBR.DBF", reference_dir / "DBF" / "TCNESBR.dbf"):
        if not path.is_file():
            continue
        table = DBF(str(path), load=False, encoding="cp850", char_decode_errors="replace", ignore_missing_memofile=True)
        fields = {field.name.upper() for field in table.fields}
        if {"CNES", "NOMEFANT"}.issubset(fields):
            connection.executemany(
                """INSERT INTO facilities (cnes, name) VALUES (?, ?)
                   ON CONFLICT (cnes) DO UPDATE SET name = excluded.name""",
                (
                    (cnes, name) for row in table
                    if (cnes := str(row.get("CNES") or "").strip())
                    and cnes in allowed_cnes
                    and re.fullmatch(r"\d{7}", cnes)
                    and (name := str(row.get("NOMEFANT") or "").strip())
                ),
            )
        break


def import_directory(
    data_dir: Path = HOSPITAL_DATA_DIR,
    database_path: Path | None = None,
    reference_dir: Path = REFERENCE_DIR,
    temp_dir: Path = TEMP_DIR,
    limit_files: int | None = None,
    on_progress: ProgressCallback | None = None,
    files: list[Path] | None = None,
) -> dict:
    if database_path is None:
        database_path = active_database_path()
    initialize_database(database_path)
    registry = load_cnes_registry(HOSPITAL_CNES_FILE)
    allowed_cnes = set(registry)
    filter_signature = cnes_filter_signature(registry)
    files = discover_files(data_dir) if files is None else sorted(files, key=lambda path: path.name.upper())
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo RDSP DBC encontrado em {data_dir}")
    if any(not FILE_PATTERN.fullmatch(path.name) or not path.is_file() for path in files):
        raise ValueError("A lista de importação contém um arquivo inválido.")
    if limit_files is not None:
        if limit_files < 1:
            raise ValueError("O limite de arquivos deve ser positivo.")
        files = files[:limit_files]

    summary = {"total_files": len(files), "imported": 0, "skipped": 0, "errors": []}
    with connect(database_path) as connection:
        for index, path in enumerate(files, start=1):
            if on_progress:
                on_progress({"current": index, "total": len(files), "file": path.name, "status": "processing"})
            try:
                result = _import_one(
                    path, data_dir, connection, allowed_cnes, filter_signature, temp_dir
                )
                summary["imported" if result["status"] == "imported" else "skipped"] += 1
                if on_progress:
                    on_progress({"current": index, "total": len(files), "status": "processing", **result})
            except Exception as exc:
                connection.rollback()
                error = {"file": path.name, "error": str(exc)}
                summary["errors"].append(error)
                if on_progress:
                    on_progress({"current": index, "total": len(files), "status": "error", **error})
        _load_references(connection, reference_dir, allowed_cnes)
        connection.executemany(
            """INSERT INTO facilities (cnes, name) VALUES (?, ?)
               ON CONFLICT (cnes) DO UPDATE SET name = excluded.name""",
            ((cnes, name) for cnes, name in registry.items()),
        )
        connection.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa agregados dos DBCs reduzidos do SIH/SUS.")
    parser.add_argument("--limit-files", type=int)
    args = parser.parse_args()
    result = import_directory(limit_files=args.limit_files, on_progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
