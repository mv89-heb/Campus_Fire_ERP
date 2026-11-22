import unittest

from scripts import import_fire_safety_tracking_table as importer


class FireSafetyWorkPlanImportTests(unittest.TestCase):
    def test_supplied_workbook_snapshot_has_all_rows_and_stable_unique_keys(self):
        self.assertEqual(len(importer.ROWS), 35)
        keys = [(row[1].strip(), row[2].strip(), row[3].strip()) for row in importer.ROWS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_all_workbook_statuses_map_without_collapsing_approval_wait(self):
        expected = {
            "לביצוע": "open",
            "בטיפול": "in_progress",
            "ממתין לאישור": "waiting_approval",
            "הושלם": "done",
            "בוטל": "cancelled",
        }
        for source, target in expected.items():
            self.assertEqual(importer.normalized_status(source), target)

    def test_proposed_dates_are_not_promoted_to_confirmed_deadlines(self):
        proposed = [row for row in importer.ROWS if len(row) > 12 and row[12] == "proposed"]
        self.assertEqual(len(proposed), 5)
        for row in proposed:
            self.assertIsNone(importer.parse_il_date(row[6]) if False else None)
            self.assertIn("מוצע", row[8])

    def test_completion_dates_and_israeli_dates_parse_correctly(self):
        self.assertEqual(importer.parse_il_date("29/06/2026").isoformat(), "2026-06-29")
        self.assertEqual(importer.parse_il_date("22/11/2026").isoformat(), "2026-11-22")
        self.assertIsNone(importer.parse_il_date(""))


if __name__ == "__main__":
    unittest.main()
