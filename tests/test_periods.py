import unittest

from app.periods import (
    display_month,
    month_sequence,
    previous_year_month,
    validate_month,
)


class PeriodTests(unittest.TestCase):
    def test_month_sequence_crosses_year(self):
        self.assertEqual(
            month_sequence("2025-11", "2026-02"),
            ["202511", "202512", "202601", "202602"],
        )

    def test_previous_year_month(self):
        self.assertEqual(previous_year_month("202601"), "202501")

    def test_rejects_reversed_period(self):
        with self.assertRaises(ValueError):
            month_sequence("2026-02", "2026-01")

    def test_rejects_invalid_month(self):
        with self.assertRaises(ValueError):
            validate_month("2026-13")

    def test_display_month(self):
        self.assertEqual(display_month("202602"), "Fev/2026")


if __name__ == "__main__":
    unittest.main()
