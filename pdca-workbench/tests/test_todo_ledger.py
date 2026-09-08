from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.sync_todo_ledger import HEADERS, MAX_DATA_ROWS, build_updates, main


class LedgerSafetyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
