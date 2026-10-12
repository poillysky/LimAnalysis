"""SN / 唯一键列识别：配置优先 + *CoverSN 通配。"""

from __future__ import annotations

import unittest
from unittest import mock

from app.core import sn_column


class PickSnColumnTest(unittest.TestCase):
    def test_prefers_project_config(self) -> None:
        cols = ["Machine", "CCoverSN", "FCoverSN"]
        project = {"project_id": "p1", "unique_key": {"column": "CCoverSN"}}
        self.assertEqual(sn_column.pick_sn_column(cols, project), "CCoverSN")

    def test_bcoversn_without_config(self) -> None:
        cols = ["机台", "BCoverSN", "模穴"]
        with (
            mock.patch.object(
                sn_column, "_system_configured_column", return_value="FCoverSN"
            ),
            mock.patch.object(sn_column, "_etl_configured_column", return_value=""),
        ):
            self.assertEqual(
                sn_column.pick_sn_column(cols, {"project_id": "x"}), "BCoverSN"
            )

    def test_coversn_wildcard_dcoversn(self) -> None:
        cols = ["机台", "DCoverSN", "模穴"]
        with mock.patch.object(sn_column, "configured_sn_candidates", return_value=["FCoverSN"]):
            self.assertEqual(sn_column.pick_sn_column(cols), "DCoverSN")

    def test_system_default_when_present(self) -> None:
        cols = ["FCoverSN", "BCoverSN"]
        with mock.patch.object(
            sn_column, "configured_sn_candidates", return_value=["FCoverSN"]
        ):
            self.assertEqual(sn_column.pick_sn_column(cols), "FCoverSN")

    def test_etl_config_over_system(self) -> None:
        cols = ["X", "CCoverSN"]
        project = {"project_id": "whale"}
        with (
            mock.patch.object(
                sn_column, "_project_configured_column", return_value=""
            ),
            mock.patch.object(
                sn_column, "_etl_configured_column", return_value="CCoverSN"
            ),
            mock.patch.object(
                sn_column, "_system_configured_column", return_value="FCoverSN"
            ),
        ):
            self.assertEqual(sn_column.pick_sn_column(cols, project), "CCoverSN")

    def test_case_insensitive(self) -> None:
        cols = ["bcoversn"]
        project = {"unique_key": {"column": "BCoverSN"}}
        self.assertEqual(sn_column.pick_sn_column(cols, project), "bcoversn")

    def test_missing_returns_none(self) -> None:
        with mock.patch.object(sn_column, "configured_sn_candidates", return_value=[]):
            self.assertIsNone(sn_column.pick_sn_column(["机台", "模穴"]))


class ResolveUniqueKeyNameTest(unittest.TestCase):
    def test_falls_back_to_fcoversn(self) -> None:
        with mock.patch.object(sn_column, "configured_sn_candidates", return_value=[]):
            self.assertEqual(sn_column.resolve_unique_key_name(None), "FCoverSN")

    def test_uses_first_configured(self) -> None:
        project = {"unique_key": {"column": "CCoverSN"}}
        self.assertEqual(sn_column.resolve_unique_key_name(project), "CCoverSN")


if __name__ == "__main__":
    unittest.main()
