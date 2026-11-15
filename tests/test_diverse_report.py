import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import ingest, main
from app.cnes import cnes_filter_signature
from app.database import connect, initialize_database


class DiverseImportTests(unittest.TestCase):
    def test_schema_upgrade_marks_existing_sources_for_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE source_files ("
                "id INTEGER PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, "
                "size_bytes INTEGER NOT NULL, modified_ns INTEGER NOT NULL, "
                "record_count INTEGER NOT NULL, "
                "imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO source_files "
                "(relative_path, size_bytes, modified_ns, record_count) "
                "VALUES ('old.dbc', 1, 1, 2)"
            )
            connection.commit()
            connection.close()

            initialize_database(database_path)

            with connect(database_path) as connection:
                marker = connection.execute(
                    "SELECT demographics_version FROM source_files"
                ).fetchone()["demographics_version"]
                table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'production_demographics'"
                ).fetchone()
            self.assertEqual(marker, 0)
            self.assertIsNotNone(table)

    def test_import_persists_aggregated_dimensions_and_refreshes_legacy_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "source"
            data_dir.mkdir()
            path = data_dir / "PASP2601a.dbc"
            path.write_bytes(b"fixture")
            database_path = root / "test.sqlite3"
            initialize_database(database_path)
            temp_dir = root / "temp"

            rows = [
                {
                    "PA_CODUNI": "1234567",
                    "PA_MVM": "202601",
                    "PA_PROC_ID": "0101010010",
                    "PA_QTDPRO": 3,
                    "PA_QTDAPR": 2,
                    "PA_VALPRO": 4,
                    "PA_VALAPR": 3,
                    "PA_FLIDADE": "1",
                    "PA_IDADE": "030",
                    "PA_SEXO": "F",
                    "PA_RACACOR": "03",
                    "PA_CIDPRI": "E780",
                    "PA_CIDSEC": "0000",
                    "PA_CIDCAS": "0000",
                },
                {
                    "PA_CODUNI": "1234567",
                    "PA_MVM": "202601",
                    "PA_PROC_ID": "0101010010",
                    "PA_QTDPRO": 1,
                    "PA_QTDAPR": 1,
                    "PA_VALPRO": 2,
                    "PA_VALAPR": 2,
                    "PA_FLIDADE": "1",
                    "PA_IDADE": "030",
                    "PA_SEXO": "F",
                    "PA_RACACOR": "03",
                    "PA_CIDPRI": "E780",
                    "PA_CIDSEC": "0000",
                    "PA_CIDCAS": "0000",
                },
            ]
            fields = set().union(*(row.keys() for row in rows))

            class FakeTable:
                def __init__(self):
                    self.fields = [SimpleNamespace(name=name) for name in fields]

                def __iter__(self):
                    return iter(rows)

            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            try:
                with patch.object(ingest, "dbc2dbf"), patch.object(
                    ingest, "DBF", lambda *_args, **_kwargs: FakeTable()
                ):
                    result = ingest._import_one(
                        path,
                        data_dir,
                        connection,
                        {"1234567"},
                        cnes_filter_signature({"1234567": "Unidade"}),
                        temp_dir,
                    )

                    self.assertEqual(result["status"], "imported")
                    row = connection.execute(
                        "SELECT age_flag, age_value, sex, race, cid_primary, "
                        "submitted_quantity, approved_quantity "
                        "FROM production_demographics"
                    ).fetchone()
                    self.assertEqual(
                        tuple(row),
                        ("1", "030", "F", "03", "E780", 4, 3),
                    )

                    connection.execute(
                        "UPDATE source_files SET demographics_version = 0"
                    )
                    connection.commit()
                    refreshed = ingest._import_one(
                        path,
                        data_dir,
                        connection,
                        {"1234567"},
                        cnes_filter_signature({"1234567": "Unidade"}),
                        temp_dir,
                    )

                self.assertEqual(refreshed["status"], "imported")
                version = connection.execute(
                    "SELECT demographics_version FROM source_files"
                ).fetchone()[0]
                self.assertEqual(version, ingest.DEMOGRAPHICS_VERSION)
            finally:
                connection.close()


class DiverseReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "test.sqlite3"
        initialize_database(self.database_path)
        with connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO source_files "
                "(relative_path, size_bytes, modified_ns, record_count, demographics_version) "
                "VALUES ('fixture.dbc', 1, 1, 2, ?)",
                (ingest.DEMOGRAPHICS_VERSION,),
            )
            source_id = connection.execute(
                "SELECT id FROM source_files WHERE relative_path = 'fixture.dbc'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO production_demographics "
                "(source_file_id, cnes, competence, procedure_code, age_flag, age_value, "
                "sex, race, cid_primary, cid_secondary, cid_associated, "
                "submitted_quantity, approved_quantity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        source_id, "1234567", "202601", "0301010010", "1", "030",
                        "F", "03", "E780", "0000", "0000", 2, 2,
                    ),
                    (
                        source_id, "1234567", "202601", "0301010010", "1", "065",
                        "M", "01", "A09", "0000", "0000", 3, 3,
                    ),
                ],
            )
            connection.commit()
        self.connect_patch = patch.object(
            main, "connect", lambda: connect(self.database_path)
        )
        self.registry_patch = patch.object(
            main,
            "load_cnes_registry",
            return_value={"1234567": "Unidade A"},
        )
        self.connect_patch.start()
        self.registry_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        self.connect_patch.stop()
        self.temp.cleanup()

    def test_diverse_report_aggregates_categories_with_approved_quantity(self):
        result = main.get_diverse_report(
            start="2026-01",
            end="2026-01",
            cnes=None,
        )

        self.assertEqual(result["total_approved_quantity"], 5)
        self.assertEqual(result["units"], 1)
        self.assertEqual(result["pending_reimport_files"], 0)
        self.assertEqual(
            [(row["label"], row["quantity"]) for row in result["dimensions"]["sex"]["items"]],
            [("Masculino", 3), ("Feminino", 2)],
        )
        self.assertEqual(
            result["dimensions"]["race"]["items"][0]["label"],
            "Branca",
        )
        self.assertEqual(
            result["dimensions"]["cid_primary"]["items"][0]["label"],
            "A09",
        )
        self.assertEqual(
            result["dimensions"]["age"]["total"],
            5,
        )

    def test_diverse_report_rejects_reversed_period(self):
        with self.assertRaises(HTTPException):
            main.get_diverse_report(start="2026-02", end="2026-01")


if __name__ == "__main__":
    unittest.main()
