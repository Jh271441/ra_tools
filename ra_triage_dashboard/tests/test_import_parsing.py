from __future__ import annotations

import io
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl

from ra_triage_dashboard.app.import_parsing import (
    normalize_model_row,
    parse_source_bytes,
)
from ra_triage_dashboard.app.filenames import safe_filename


class ImportParsingTest(unittest.TestCase):
    def test_long_upload_filename_keeps_spreadsheet_suffix(self) -> None:
        filename = f"{'stage1_result_' * 12}0508.xlsx"
        safe = safe_filename(filename)
        self.assertLessEqual(len(safe), 120)
        self.assertTrue(safe.endswith(".xlsx"))

    def test_stage1_true_stuck_aliases_share_one_model_label(self) -> None:
        for value in ("真实卡住", "非误触发"):
            with self.subTest(value=value):
                row = normalize_model_row(
                    {"issue_id": "cn31842459", "model_label": value}
                )
                self.assertIsNotNone(row)
                assert row is not None
                self.assertEqual(row["model_label"], "真实卡住")

    def test_stage1_prediction_column_is_supported(self) -> None:
        row = normalize_model_row(
            {"issue_id": "cn31842459", "stage1_prediction": "非误触发"}
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["model_label"], "真实卡住")

    def test_normalize_model_row_preserves_supported_contract(self) -> None:
        row = normalize_model_row(
            {
                "issue_id": "cn31842459",
                "ra_stuck_auto_result": "误触发",
                "ra_stuck_auto_result_info": {
                    "reason": "排队误判",
                    "confidence": 0.9,
                },
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["model_label"], "误触发")
        self.assertEqual(row["model_reason"], "排队误判")
        self.assertEqual(row["model_confidence"], 0.9)

    def test_parse_xlsx_closes_and_returns_rows(self) -> None:
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "predictions"
        sheet.append(["issue_id", "model_label"])
        sheet.append(["cn31842459", "误触发"])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()

        rows, metadata = parse_source_bytes("results.xlsx", output.getvalue())
        self.assertEqual(rows, [{"issue_id": "cn31842459", "model_label": "误触发"}])
        self.assertEqual(metadata, {"sheet": "predictions"})

    def test_parse_xlsx_rejects_non_zip_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "有效的 Office"):
            parse_source_bytes("results.xlsx", b"not-an-office-file")

    def test_parse_xlsx_rejects_extreme_compression_ratio(self) -> None:
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", "0" * 2_000_000)
        with self.assertRaisesRegex(ValueError, "压缩比异常"):
            parse_source_bytes("results.xlsx", output.getvalue())


if __name__ == "__main__":
    unittest.main()
