import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import database, main
from app.cnes import load_cnes_registry
from app.database import initialize_database


class UnitSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ambulatory_path = self.root / "CNES_TAUBATE.txt"
        self.hospital_path = self.root / "CNES_TAUBATE_HOSPITALAR.txt"
        self.ambulatory_path.write_text(
            "CNES\tNome da Unidade\n1234567\tUnidade A\n", encoding="utf-8"
        )
        self.hospital_path.write_text(
            "CNES\tNome da Unidade\n7654321\tHospital B\n", encoding="utf-8"
        )
        self.patches = [
            patch.object(main, "CNES_FILE", self.ambulatory_path),
            patch.object(main, "HOSPITAL_CNES_FILE", self.hospital_path),
            patch.object(
                main,
                "prune_unlisted_units",
                return_value={"ambulatory": 0, "hospital": 0, "facilities": 0},
            ),
        ]
        for mocked in self.patches:
            mocked.start()

    def tearDown(self):
        for mocked in reversed(self.patches):
            mocked.stop()
        self.temp.cleanup()

    def test_saves_both_unit_registries(self):
        settings = main.UnitSettings(
            ambulatory=[main.UnitEntry(cnes="1234567", name="Unidade Atualizada")],
            hospital=[main.UnitEntry(cnes="7654321", name="Hospital Atualizado")],
        )

        result = main.save_unit_settings(settings)

        self.assertIn("Unidades salvas", result["message"])
        self.assertEqual(
            load_cnes_registry(self.ambulatory_path),
            {"1234567": "Unidade Atualizada"},
        )
        self.assertEqual(
            load_cnes_registry(self.hospital_path),
            {"7654321": "Hospital Atualizado"},
        )

    def test_rejects_duplicate_cnes_without_writing(self):
        settings = main.UnitSettings(
            ambulatory=[
                main.UnitEntry(cnes="1234567", name="Unidade A"),
                main.UnitEntry(cnes="1234567", name="Unidade B"),
            ],
            hospital=[main.UnitEntry(cnes="7654321", name="Hospital B")],
        )

        with self.assertRaises(HTTPException):
            main.save_unit_settings(settings)

        self.assertEqual(
            load_cnes_registry(self.ambulatory_path), {"1234567": "Unidade A"}
        )


class DatabaseSettingsTests(unittest.TestCase):
    def test_prunes_unlisted_production_and_facility_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "test.sqlite3"
            initialize_database(database_path)
            with database.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO source_files (relative_path, size_bytes, modified_ns, record_count) "
                    "VALUES ('pa.dbc', 1, 1, 2)"
                )
                connection.execute(
                    "INSERT INTO hospital_source_files "
                    "(relative_path, size_bytes, modified_ns, record_count) "
                    "VALUES ('sih.dbc', 1, 1, 2)"
                )
                connection.executemany(
                    "INSERT INTO production (source_file_id, cnes, competence, procedure_code) "
                    "VALUES (1, ?, '202601', '0301010010')",
                    [("1234567",), ("9999999",)],
                )
                connection.executemany(
                    "INSERT INTO production_demographics "
                    "(source_file_id, cnes, competence, procedure_code, approved_quantity) "
                    "VALUES (1, ?, '202601', '0301010010', 1)",
                    [("1234567",), ("9999999",)],
                )
                connection.executemany(
                    "INSERT INTO hospital_production "
                    "(source_file_id, cnes, competence, procedure_code) "
                    "VALUES (1, ?, '202601', '0303010010')",
                    [("7654321",), ("9999999",)],
                )
                connection.executemany(
                    "INSERT INTO facilities (cnes, name) VALUES (?, ?)",
                    [
                        ("1234567", "Ambulatorial"),
                        ("7654321", "Hospital"),
                        ("9999999", "Fora da lista"),
                    ],
                )
                connection.commit()

            removed = database.prune_unlisted_units(
                {"1234567"}, {"7654321"}, database_path
            )

            self.assertEqual(
                removed,
                {"ambulatory": 1, "demographics": 1, "hospital": 1, "facilities": 1},
            )
            with database.connect(database_path) as connection:
                self.assertEqual(
                    [row["cnes"] for row in connection.execute("SELECT cnes FROM production")],
                    ["1234567"],
                )
                self.assertEqual(
                    [
                        row["cnes"]
                        for row in connection.execute(
                            "SELECT cnes FROM production_demographics"
                        )
                    ],
                    ["1234567"],
                )
                self.assertEqual(
                    [row["cnes"] for row in connection.execute("SELECT cnes FROM hospital_production")],
                    ["7654321"],
                )
                self.assertEqual(
                    {row["cnes"] for row in connection.execute("SELECT cnes FROM facilities")},
                    {"1234567", "7654321"},
                )

    def test_uploads_and_persists_selected_sqlite_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.sqlite3"
            initialize_database(source_path)
            connection = sqlite3.connect(source_path)
            try:
                connection.execute("CREATE TABLE fixture (value TEXT)")
                connection.execute("INSERT INTO fixture VALUES ('kept')")
                connection.commit()
            finally:
                connection.close()
            storage_path = root / "databases"
            selection_path = root / "selected_database.txt"
            uploaded_file = SimpleNamespace(
                filename="meu banco.sqlite3",
                file=io.BytesIO(source_path.read_bytes()),
            )
            patches = [
                patch.object(main, "DATABASE_STORAGE_DIR", storage_path),
                patch.object(database, "DATABASE_STORAGE_DIR", storage_path),
                patch.object(database, "DATABASE_SELECTION_FILE", selection_path),
            ]
            for mocked in patches:
                mocked.start()
            try:
                result = main.upload_database(uploaded_file)

                selected_path = database.active_database_path()
                self.assertEqual(selected_path.name, result["name"])
                self.assertEqual(selection_path.read_text(encoding="utf-8"), result["name"])
                with database.connect() as connection:
                    self.assertEqual(
                        connection.execute("SELECT value FROM fixture").fetchone()[0],
                        "kept",
                    )
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

    def test_rejects_non_sqlite_upload(self):
        upload = SimpleNamespace(
            filename="invalid.sqlite3", file=io.BytesIO(b"not a database")
        )

        with self.assertRaises(HTTPException) as error:
            main.upload_database(upload)

        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
