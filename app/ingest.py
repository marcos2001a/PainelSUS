"""
Módulo de ingestão de dados DBC

Processa arquivos DBC e os importa para o banco de dados SQLite.
"""

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

from .config import DATA_DIR, DATABASE_PATH, REFERENCE_DIR, TEMP_DIR
from .database import connect, initialize_database

FILE_PATTERN = re.compile(r"^PASP(\d{2})(\d{2})[a-d]\.dbc$", re.IGNORECASE)
REQUIRED_FIELDS = {
    "PA_CODUNI",
    "PA_MVM",
    "PA_PROC_ID",
    "PA_QTDPRO",
    "PA_QTDAPR",
    "PA_VALPRO",
    "PA_VALAPR",
}
CHUNK_SIZE = 50_000
ProgressCallback = Callable[[dict], None]


def discover_files(data_dir: Path = DATA_DIR) -> list[Path]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Pasta de dados não encontrada: {data_dir}")
    files = [
        path
        for path in data_dir.iterdir()
        if path.is_file() and FILE_PATTERN.fullmatch(path.name)
    ]
    return sorted(files, key=lambda path: path.name.upper())


def _integer(value) -> int:
    if value in (None, ""):
        return 0
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _cents(value) -> int:
    if value in (None, ""):
        return 0
    amount = Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return int(amount * 100)


def _flush(
    connection: sqlite3.Connection,
    source_id: int,
    totals: dict[tuple[str, str, str], list[int]],
) -> int:
    if not totals:
        return 0
    connection.executemany(
        """
        INSERT INTO production (
            source_file_id, cnes, competence, procedure_code,
            submitted_quantity, approved_quantity,
            submitted_value_cents, approved_value_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
            source_file_id, cnes, competence, procedure_code
        ) DO UPDATE SET
            submitted_quantity =
                production.submitted_quantity + excluded.submitted_quantity,
            approved_quantity =
                production.approved_quantity + excluded.approved_quantity,
            submitted_value_cents =
                production.submitted_value_cents + excluded.submitted_value_cents,
            approved_value_cents =
                production.approved_value_cents + excluded.approved_value_cents
        """,
        [
            (source_id, *key, *values)
            for key, values in totals.items()
        ],
    )
    count = len(totals)
    totals.clear()
    return count


def _import_one(
    path: Path,
    data_dir: Path,
    connection: sqlite3.Connection,
    temp_dir: Path = TEMP_DIR,
) -> dict:
    stat = path.stat()
    relative_path = path.relative_to(data_dir).as_posix()
    previous = connection.execute(
        """
        SELECT id, size_bytes, modified_ns
        FROM source_files
        WHERE relative_path = ?
        """,
        (relative_path,),
    ).fetchone()
    if (
        previous
        and previous["size_bytes"] == stat.st_size
        and previous["modified_ns"] == stat.st_mtime_ns
    ):
        return {"file": path.name, "status": "skipped_unchanged"}

    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, dbf_name = tempfile.mkstemp(
        prefix="tabwin_pa_",
        suffix=".dbf",
        dir=temp_dir,
    )
    os.close(fd)
    dbf_path = Path(dbf_name)
    try:
        dbc2dbf(str(path), str(dbf_path))
        table = DBF(
            str(dbf_path),
            load=False,
            encoding="cp850",
            char_decode_errors="replace",
            ignore_missing_memofile=True,
        )
        field_names = {field.name.upper() for field in table.fields}
        missing = REQUIRED_FIELDS - field_names
        if missing:
            raise ValueError(
                f"{path.name}: faltam campos necessários: "
                f"{', '.join(sorted(missing))}"
            )

        connection.execute("BEGIN IMMEDIATE")
        if previous:
            source_id = previous["id"]
            connection.execute(
                "DELETE FROM production WHERE source_file_id = ?",
                (source_id,),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO source_files (
                    relative_path, size_bytes, modified_ns, record_count
                ) VALUES (?, ?, ?, 0)
                """,
                (relative_path, stat.st_size, stat.st_mtime_ns),
            )
            source_id = cursor.lastrowid

        totals: dict[tuple[str, str, str], list[int]] = defaultdict(
            lambda: [0, 0, 0, 0]
        )
        record_count = 0
        skipped_rows = 0
        grouped_rows = 0
        for row in table:
            record_count += 1
            cnes = str(row.get("PA_CODUNI") or "").strip()
            competence = str(row.get("PA_MVM") or "").strip()
            procedure = str(row.get("PA_PROC_ID") or "").strip()
            if (
                not re.fullmatch(r"\d{7}", cnes)
                or not re.fullmatch(r"(?:19|20)\d{4}", competence)
                or not re.fullmatch(r"\d{1,10}", procedure)
                or not 1 <= int(competence[4:]) <= 12
            ):
                skipped_rows += 1
                continue

            values = totals[(cnes, competence, procedure)]
            values[0] += _integer(row.get("PA_QTDPRO"))
            values[1] += _integer(row.get("PA_QTDAPR"))
            values[2] += _cents(row.get("PA_VALPRO"))
            values[3] += _cents(row.get("PA_VALAPR"))
            if record_count % CHUNK_SIZE == 0:
                grouped_rows += _flush(connection, source_id, totals)

        grouped_rows += _flush(connection, source_id, totals)
        connection.execute(
            """
            UPDATE source_files
            SET size_bytes = ?, modified_ns = ?, record_count = ?,
                imported_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (stat.st_size, stat.st_mtime_ns, record_count, source_id),
        )
        connection.commit()
        return {
            "file": path.name,
            "status": "imported",
            "records": record_count,
            "groups": grouped_rows,
            "skipped_rows": skipped_rows,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        dbf_path.unlink(missing_ok=True)


def _load_references(connection: sqlite3.Connection, reference_dir: Path) -> None:
    facility_file = reference_dir / "CNESBR.dbf"
    if facility_file.is_file():
        table = DBF(
            str(facility_file),
            load=False,
            encoding="cp850",
            char_decode_errors="replace",
            ignore_missing_memofile=True,
        )
        fields = {field.name.upper() for field in table.fields}
        name_field = "FANTASIA" if "FANTASIA" in fields else "NOMEFANT"
        if "CNES" in fields and name_field in fields:
            connection.executemany(
                """
                INSERT INTO facilities (cnes, name) VALUES (?, ?)
                ON CONFLICT (cnes) DO UPDATE SET name = excluded.name
                """,
                (
                    (
                        str(row.get("CNES") or "").strip(),
                        str(row.get(name_field) or "").strip(),
                    )
                    for row in table
                    if re.fullmatch(r"\d{7}", str(row.get("CNES") or "").strip())
                    and str(row.get(name_field) or "").strip()
                ),
            )

    procedure_sources = (
        (reference_dir / "DBF" / "TPROC.DBF", "TPROC.DBF"),
        (reference_dir / "DBF" / "TPROC10.DBF", "TPROC10.DBF"),
        (reference_dir / "DBF" / "TPROCUNI.DBF", "TPROCUNI.DBF"),
    )
    for path, source in procedure_sources:
        if not path.is_file():
            continue
        table = DBF(
            str(path),
            load=False,
            encoding="cp850",
            char_decode_errors="replace",
            ignore_missing_memofile=True,
        )
        fields = {field.name.upper() for field in table.fields}
        if not {"IP_COD", "IP_DSCR"}.issubset(fields):
            continue
        connection.executemany(
            """
            INSERT INTO procedures (code, description, source)
            VALUES (?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET
                description = excluded.description,
                source = excluded.source
            """,
            (
                (code, description, source)
                for row in table
                if (code := str(row.get("IP_COD") or "").strip())
                and (description := str(row.get("IP_DSCR") or "").strip())
            ),
        )


def import_directory(
    data_dir: Path = DATA_DIR,
    database_path: Path = DATABASE_PATH,
    reference_dir: Path = REFERENCE_DIR,
    temp_dir: Path = TEMP_DIR,
    limit_files: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    initialize_database(database_path)
    files = discover_files(data_dir)
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo PASP DBC encontrado em {data_dir}")
    if limit_files is not None:
        if limit_files < 1:
            raise ValueError("O limite de arquivos deve ser positivo.")
        files = files[:limit_files]

    summary = {"total_files": len(files), "imported": 0, "skipped": 0, "errors": []}
    with connect(database_path) as connection:
        for index, path in enumerate(files, start=1):
            if on_progress:
                on_progress(
                    {
                        "current": index,
                        "total": len(files),
                        "file": path.name,
                        "status": "processing",
                    }
                )
            try:
                result = _import_one(path, data_dir, connection, temp_dir)
                if result["status"] == "imported":
                    summary["imported"] += 1
                else:
                    summary["skipped"] += 1
                if on_progress:
                    on_progress(
                        {
                            "current": index,
                            "total": len(files),
                            "status": "processing",
                            **result,
                        }
                    )
            except Exception as exc:
                connection.rollback()
                error = {"file": path.name, "error": str(exc)}
                summary["errors"].append(error)
                if on_progress:
                    on_progress(
                        {
                            "current": index,
                            "total": len(files),
                            "status": "error",
                            **error,
                        }
                    )
        _load_references(connection, reference_dir)
        connection.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa os DBCs de produção ambulatorial para SQLite."
    )
    parser.add_argument("--limit-files", type=int)
    args = parser.parse_args()

    def report(event: dict) -> None:
        print(json.dumps(event, ensure_ascii=False), flush=True)

    result = import_directory(
        limit_files=args.limit_files,
        on_progress=report,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
