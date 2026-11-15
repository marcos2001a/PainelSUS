import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.database import connect, initialize_database


class GeneralReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "test.sqlite3"
        initialize_database(self.database_path)
        with connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO source_files "
                "(relative_path, size_bytes, modified_ns, record_count) "
                "VALUES ('fixture.dbc', 1, 1, 4)"
            )
            source_file_id = connection.execute(
                "SELECT id FROM source_files WHERE relative_path = 'fixture.dbc'"
            ).fetchone()["id"]
            connection.executemany(
                "INSERT INTO production "
                "(source_file_id, cnes, competence, procedure_code, approved_quantity) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (source_file_id, "1234567", "202601", "0201010010", 10),
                    (source_file_id, "1234567", "202601", "0301010010", 3),
                    (source_file_id, "1234567", "202501", "0201010010", 6),
                    (source_file_id, "1234567", "202501", "0301010010", 4),
                    (source_file_id, "7654321", "202501", "0301010010", 5),
                ],
            )
            connection.commit()
        self.patches = [
            patch.object(main, "connect", lambda: connect(self.database_path)),
            patch.object(
                main,
                "load_cnes_registry",
                return_value={"1234567": "Unidade A", "7654321": "Unidade B"},
            ),
        ]
        for mocked in self.patches:
            mocked.start()

    def tearDown(self):
        for mocked in reversed(self.patches):
            mocked.stop()
        self.temp.cleanup()

    def test_general_report_sums_categories_and_comparison(self):
        result = main.get_general_report("2026-01", "2026-01", True)

        self.assertTrue(result["exams"])
        self.assertTrue(result["procedures"])
        self.assertEqual(result["summary"]["exams"], 10)
        self.assertEqual(result["summary"]["procedures"], 3)
        self.assertEqual(result["summary"]["total"], 13)
        self.assertEqual(result["summary"]["previous_total"], 15)
        self.assertEqual(result["summary"]["total_difference"], -2)
        self.assertEqual(result["summary"]["total_percentage"], -13.3)
        self.assertEqual([row["cnes"] for row in result["rows"]], ["1234567", "7654321"])
        self.assertEqual(result["rows"][0]["previous_total"], 10)
        self.assertEqual(result["rows"][1]["total"], 0)

    def test_general_report_rejects_reversed_period(self):
        with self.assertRaises(HTTPException):
            main.get_general_report("2026-02", "2026-01")

    def test_general_report_can_include_only_exams(self):
        result = main.get_general_report(
            "2026-01", "2026-01", True, exams=True, procedures=False
        )

        self.assertTrue(result["exams"])
        self.assertFalse(result["procedures"])
        self.assertEqual(result["summary"]["total"], 10)
        self.assertEqual(result["summary"]["previous_total"], 6)
        self.assertEqual([row["cnes"] for row in result["rows"]], ["1234567"])

    def test_general_report_requires_at_least_one_category(self):
        with self.assertRaises(HTTPException):
            main.get_general_report(
                "2026-01", "2026-01", exams=False, procedures=False
            )


if __name__ == "__main__":
    unittest.main()
