"""inspection 拆分出的纯函数簇单测。

覆盖 inspection_parts 的 dates / filenames 两个纯函数模块，
以及 inspection 门面仍能正确透传（保证拆分后对外行为不变）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core import inspection
from app.core.inspection_parts import dates, filenames


class DateHelpersTest(unittest.TestCase):
    def test_sort_key_normalizes_separators(self) -> None:
        self.assertEqual(dates.appearance_date_sort_key("2026.10.07"), "20261007")
        self.assertEqual(dates.appearance_date_sort_key("2026-10-07"), "20261007")
        self.assertEqual(dates.appearance_date_sort_key("20261007"), "20261007")

    def test_is_date_dir(self) -> None:
        self.assertTrue(dates.appearance_is_date_dir("20261007"))
        self.assertTrue(dates.appearance_is_date_dir("2026.10.07"))
        self.assertTrue(dates.appearance_is_date_dir("2026-10-07"))
        self.assertFalse(dates.appearance_is_date_dir("2026.10.7"))
        self.assertFalse(dates.appearance_is_date_dir("random"))

    def test_aliases_include_all_forms(self) -> None:
        aliases = dates.appearance_date_aliases("2026.10.07")
        self.assertIn("20261007", aliases)
        self.assertIn("2026.10.07", aliases)
        self.assertIn("2026-10-07", aliases)

    def test_aliases_empty_input(self) -> None:
        self.assertEqual(dates.appearance_date_aliases(""), [])

    def test_resolve_date_dir_finds_dotted_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026.10.07").mkdir()
            resolved = dates.appearance_resolve_date_dir(root, "20261007")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.name, "2026.10.07")

    def test_resolve_date_dir_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                dates.appearance_resolve_date_dir(Path(tmp), "20260101")
            )


class FilenameHelpersTest(unittest.TestCase):
    def test_extract_cavity_from_comma_tail(self) -> None:
        self.assertEqual(filenames.extract_cavity("SN001,B.jpg"), "B")

    def test_extract_cavity_from_underscore(self) -> None:
        self.assertEqual(filenames.extract_cavity("SN_001_A.png"), "A")

    def test_extract_cavity_none_found(self) -> None:
        self.assertEqual(filenames.extract_cavity("12345.jpg"), "")

    def test_extract_status_head_match(self) -> None:
        self.assertEqual(filenames.extract_status("OK,x.jpg"), "OK")

    def test_extract_status_contains_match(self) -> None:
        self.assertEqual(filenames.extract_status("a_定位NG_b.jpg"), "定位NG")

    def test_extract_status_none(self) -> None:
        self.assertEqual(filenames.extract_status("plain.jpg"), "")

    def test_extract_sn_mold_status_sn_cavity(self) -> None:
        self.assertEqual(filenames.extract_sn("OK,sample03,A.jpg"), "sample03")

    def test_extract_sn_mold_sn_cavity(self) -> None:
        self.assertEqual(filenames.extract_sn("sample03,B.jpg"), "sample03")

    def test_extract_sn_appearance_prefix_view(self) -> None:
        self.assertEqual(filenames.extract_sn("截图SN001_camLeft.jpg"), "SN001")


class FacadePassthroughTest(unittest.TestCase):
    """门面 re-export 必须与子模块行为一致（拆分不改变对外契约）。"""

    def test_facade_matches_submodule(self) -> None:
        sample = ["SN001,B.jpg", "SN_001_A.png", "x.jpg"]
        for name in sample:
            self.assertEqual(
                inspection.extract_cavity(name), filenames.extract_cavity(name)
            )
            self.assertEqual(
                inspection.extract_status(name), filenames.extract_status(name)
            )

    def test_facade_constants_exposed(self) -> None:
        self.assertIn("A", inspection.CAVITY_LETTERS)
        self.assertIn("OK", inspection.VIEWER_STATUSES)
        self.assertEqual(inspection.SOURCE_ROOT_KEYS["mold"], "mold_root_path")


if __name__ == "__main__":
    unittest.main()
