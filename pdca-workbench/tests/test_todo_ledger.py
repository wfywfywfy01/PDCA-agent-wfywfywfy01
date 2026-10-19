from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.sync_todo_ledger import HEADERS, MAX_DATA_ROWS, build_updates, main


class LedgerSafetyTests(unittest.TestCase):
    def test_current_production_volume_is_complete(self):
        rows = [[str(i)] * len(HEADERS) for i in range(3037)]
        updates = build_updates(rows)
        self.assertEqual(len(updates), 3038 * len(HEADERS))
        self.assertEqual(updates[-1], {"cell": "J3038", "value": "3036"})

    def test_corrupt_previous_row_count_cannot_allocate_unbounded_clear(self):
        with self.assertRaisesRegex(RuntimeError, "超过安全上限"):
            build_updates([], previous_row_count=MAX_DATA_ROWS + 1)

    def test_updates_clear_stale_rows(self):
        row = ["x"] * len(HEADERS)
        updates = build_updates([row], previous_row_count=3)
        by_cell = {item["cell"]: item["value"] for item in updates}
        self.assertEqual(by_cell["A2"], "x")
        self.assertEqual(by_cell["A3"], "")
        self.assertEqual(by_cell["I4"], "")

    def test_over_limit_fails_instead_of_partial_write(self):
        rows = [["x"] * len(HEADERS) for _ in range(MAX_DATA_ROWS + 1)]
        with self.assertRaisesRegex(RuntimeError, "超过安全上限"):
            build_updates(rows)

    def test_dry_run_has_no_schema_or_external_writes(self):
        with patch("scripts.sync_todo_ledger.check_db_connection", return_value=True), \
                patch("scripts.sync_todo_ledger.build_rows", return_value=[]), \
                patch("scripts.sync_todo_ledger.get_existing_doc", return_value=("", "sheet-1")), \
                patch("scripts.sync_todo_ledger.init_db") as init_db, \
                patch("scripts.sync_todo_ledger.get_or_create_doc") as create_doc, \
                patch("scripts.sync_todo_ledger.run_vertu_sync") as write_doc, \
                redirect_stdout(io.StringIO()):
            code = main(["--dry-run"])
        self.assertEqual(code, 0)
        init_db.assert_not_called()
        create_doc.assert_not_called()
        write_doc.assert_not_called()

    def test_failed_batch_preserves_high_water_for_next_cleanup(self):
        rows = [["x"] * len(HEADERS) for _ in range(401)]
        with patch("scripts.sync_todo_ledger.check_db_connection", return_value=True), \
                patch("scripts.sync_todo_ledger.init_db"), \
                patch("scripts.sync_todo_ledger.build_rows", return_value=rows), \
                patch("scripts.sync_todo_ledger.get_or_create_doc", return_value=("doc", "sheet-1")), \
                patch("scripts.sync_todo_ledger._state_int", return_value=100), \
                patch("scripts.sync_todo_ledger._set_state_value") as state, \
                patch("scripts.sync_todo_ledger.run_vertu_sync", side_effect=[(0, "", ""), (1, "", "offline")]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 1)
        state.assert_called_once_with("ledger_row_count", "401")


if __name__ == "__main__":
    unittest.main()
