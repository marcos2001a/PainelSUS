import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import hospital_ingest, ingest
from app.cnes import cnes_filter_signature, load_cnes_registry
from app.database import initialize_database


class CnesRegistryTests(unittest.TestCase):
    def test_loads_tsv_registry_and_skips_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CNES.txt"
            path.write_text("CNES\tNome da Unidade\n1234567\tUnidade Teste\n", encoding="utf-8")

            self.assertEqual(load_cnes_registry(path), {"1234567": "Unidade Teste"})

    def test_rejects_invalid_cnes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CNES.txt"
            path.write_text("CNES\tNome\n123\tUnidade\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "CNES inválido"):
                load_cnes_registry(path)

    def test_signature_depends_on_codes_not_order_or_names(self):
        first = {"1234567": "Unidade A", "7654321": "Unidade B"}
        second = {"7654321": "Outro nome", "1234567": "Unidade A"}

        self.assertEqual(cnes_filter_signature(first), cnes_filter_signature(second))


class CnesImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "source"
        self.data_dir.mkdir()
        self.database_path = self.root / "test.sqlite3"
        initialize_database(self.database_path)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.temp_dir = self.root / "temp"

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def _fake_dbf(self, fields, rows):
        class FakeTable:
            def __init__(self):
                self.fields = [SimpleNamespace(name=field) for field in fields]

            def __iter__(self):
                return iter(rows)

        return lambda *_args, **_kwargs: FakeTable()

    def test_ambulatory_import_filters_and_reprocesses_when_registry_changes(self):
        path = self.data_dir / "PASP2601a.dbc"
        path.write_bytes(b"fixture")
        rows = [
            {
                "PA_CODUNI": "1234567", "PA_MVM": "202601", "PA_PROC_ID": "0101010010",
                "PA_QTDPRO": 1, "PA_QTDAPR": 1, "PA_VALPRO": 2, "PA_VALAPR": 2,
            },
            {
                "PA_CODUNI": "7654321", "PA_MVM": "202601", "PA_PROC_ID": "0101010010",
                "PA_QTDPRO": 1, "PA_QTDAPR": 1, "PA_VALPRO": 2, "PA_VALAPR": 2,
            },
        ]
        fields = ingest.REQUIRED_FIELDS
        with patch.object(ingest, "dbc2dbf"), patch.object(
            ingest, "DBF", self._fake_dbf(fields, rows)
        ):
            result = ingest._import_one(
                path, self.data_dir, self.connection, {"1234567"},
                cnes_filter_signature({"1234567": "Unidade A"}), self.temp_dir,
            )
            self.assertEqual(result["filtered_rows"], 1)

            result = ingest._import_one(
                path, self.data_dir, self.connection, {"7654321"},
                cnes_filter_signature({"7654321": "Unidade B"}), self.temp_dir,
            )
            self.assertEqual(result["status"], "imported")
            self.assertEqual(result["filtered_rows"], 1)

        cnes = self.connection.execute("SELECT cnes FROM production").fetchall()
        self.assertEqual([row["cnes"] for row in cnes], ["7654321"])

    def test_hospital_import_filters_unlisted_cnes(self):
        path = self.data_dir / "RDSP2026.dbc"
        path.write_bytes(b"fixture")
        rows = [
            {
                "ANO_CMPT": "2026", "MES_CMPT": "1", "CNES": "2749319",
                "PROC_REA": "0303010010", "VAL_TOT": 2, "MORTE": 0, "DIAS_PERM": 1,
            },
            {
                "ANO_CMPT": "2026", "MES_CMPT": "1", "CNES": "1234567",
                "PROC_REA": "0303010010", "VAL_TOT": 2, "MORTE": 0, "DIAS_PERM": 1,
            },
        ]
        with patch.object(hospital_ingest, "dbc2dbf"), patch.object(
            hospital_ingest, "DBF", self._fake_dbf(hospital_ingest.REQUIRED_FIELDS, rows)
        ):
            result = hospital_ingest._import_one(
                path, self.data_dir, self.connection, {"2749319"},
                cnes_filter_signature({"2749319": "Hospital"}), self.temp_dir,
            )

        self.assertEqual(result["filtered_rows"], 1)
        cnes = self.connection.execute("SELECT cnes FROM hospital_production").fetchall()
        self.assertEqual([row["cnes"] for row in cnes], ["2749319"])

    def test_ambulatory_reference_import_keeps_only_registered_units(self):
        reference_file = self.root / "CNESBR.dbf"
        reference_file.touch()
        rows = [
            {"CNES": "1234567", "FANTASIA": "Unidade permitida"},
            {"CNES": "7654321", "FANTASIA": "Unidade não listada"},
        ]
        with patch.object(ingest, "DBF", self._fake_dbf({"CNES", "FANTASIA"}, rows)):
            ingest._load_references(
                self.connection, self.root, {"1234567"}
            )

        facilities = self.connection.execute(
            "SELECT cnes, name FROM facilities"
        ).fetchall()
        self.assertEqual(
            [(row["cnes"], row["name"]) for row in facilities],
            [("1234567", "Unidade permitida")],
        )

    def test_hospital_reference_import_keeps_only_registered_units(self):
        reference_dir = self.root / "references"
        dbf_dir = reference_dir / "DBF"
        dbf_dir.mkdir(parents=True)
        (dbf_dir / "TCNESBR.DBF").touch()
        rows = [
            {"CNES": "2749319", "NOMEFANT": "Hospital permitido"},
            {"CNES": "7654321", "NOMEFANT": "Hospital não listado"},
        ]
        with patch.object(
            hospital_ingest, "DBF", self._fake_dbf({"CNES", "NOMEFANT"}, rows)
        ):
            hospital_ingest._load_references(
                self.connection, reference_dir, {"2749319"}
            )

        facilities = self.connection.execute(
            "SELECT cnes, name FROM facilities"
        ).fetchall()
        self.assertEqual(
            [(row["cnes"], row["name"]) for row in facilities],
            [("2749319", "Hospital permitido")],
        )


if __name__ == "__main__":
    unittest.main()
