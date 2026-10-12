"""项目级 CSV 列名映射：规范化 + 入库前重命名。"""

from __future__ import annotations

import unittest
from typing import ClassVar
from unittest import mock

import pandas as pd

from app.core.column_map import apply_column_map, normalize_column_map
from app.core.projects import _merge_project_config
from collector import raw_loader
from collector.raw_loader import parse_csv, unique_column


class NormalizeColumnMapTest(unittest.TestCase):
    def test_list_and_aliases(self) -> None:
        raw = [
            {"source": "BCoverSN", "target": "FCoverSN"},
            {"from": "X", "to": "Y"},
            {"原名": "A", "指定名": "B"},
            {"source": "same", "target": "same"},
            {"source": "", "target": "Z"},
        ]
        self.assertEqual(
            normalize_column_map(raw),
            [
                {"source": "BCoverSN", "target": "FCoverSN"},
                {"source": "X", "target": "Y"},
                {"source": "A", "target": "B"},
            ],
        )

    def test_dict_form(self) -> None:
        self.assertEqual(
            normalize_column_map({"BCoverSN": "FCoverSN"}),
            [{"source": "BCoverSN", "target": "FCoverSN"}],
        )

    def test_dedupe_source_and_target(self) -> None:
        raw = [
            {"source": "BCoverSN", "target": "FCoverSN"},
            {"source": "bcoversn", "target": "Other"},
            {"source": "CCoverSN", "target": "FCoverSN"},
        ]
        self.assertEqual(
            normalize_column_map(raw),
            [{"source": "BCoverSN", "target": "FCoverSN"}],
        )


class ApplyColumnMapTest(unittest.TestCase):
    def test_renames_case_insensitive(self) -> None:
        frame = pd.DataFrame({"bcoversn": ["s1"], "机台": ["D1"]})
        project = {
            "column_map": [{"source": "BCoverSN", "target": "FCoverSN"}]
        }
        out = apply_column_map(frame, project)
        self.assertIn("FCoverSN", out.columns)
        self.assertNotIn("bcoversn", out.columns)
        self.assertEqual(list(out["FCoverSN"]), ["s1"])

    def test_skips_when_target_exists(self) -> None:
        frame = pd.DataFrame(
            {"BCoverSN": ["a"], "FCoverSN": ["b"], "机台": ["D1"]}
        )
        project = {
            "column_map": [{"source": "BCoverSN", "target": "FCoverSN"}]
        }
        out = apply_column_map(frame, project)
        self.assertIn("BCoverSN", out.columns)
        self.assertEqual(list(out["FCoverSN"]), ["b"])

    def test_noop_without_map(self) -> None:
        frame = pd.DataFrame({"BCoverSN": ["a"]})
        out = apply_column_map(frame, {})
        self.assertEqual(list(out.columns), ["BCoverSN"])


class IngestPipelineMockTest(unittest.TestCase):
    """模拟 CSV：BCoverSN → FCoverSN 后唯一键与 upsert 写入列。"""

    CSV = (
        "机台,模穴,BCoverSN,Result,Time\n"
        "D1,1,SN-001,OK,2026-10-12 10:00:00\n"
        "D1,2,SN-002,NG,2026-10-12 10:01:00\n"
        "D2,1,SN-003,OK,2026-10-12 10:02:00\n"
    )
    PROJECT: ClassVar[dict] = {
        "project_id": "mock_whale",
        "column_map": [{"source": "BCoverSN", "target": "FCoverSN"}],
    }

    def test_parse_map_unique_key(self) -> None:
        frame = parse_csv(self.CSV)
        self.assertIn("BCoverSN", frame.columns)
        mapped = apply_column_map(frame, self.PROJECT)
        self.assertIn("FCoverSN", mapped.columns)
        self.assertNotIn("BCoverSN", mapped.columns)
        self.assertEqual(unique_column(mapped, self.PROJECT), "FCoverSN")
        self.assertEqual(unique_column(frame, {"project_id": "x"}), "BCoverSN")

    def test_config_merge_persists_map(self) -> None:
        merged = _merge_project_config(
            {
                "machines": [],
                "owners": {},
                "column_map": [{"source": "BCoverSN", "target": "FCoverSN"}],
            }
        )
        self.assertEqual(
            merged["column_map"],
            [{"source": "BCoverSN", "target": "FCoverSN"}],
        )

    def test_upsert_uses_project_map(self) -> None:
        def fake_get_project(pid: str):
            self.assertEqual(pid, "mock_whale")
            return self.PROJECT

        with (
            mock.patch("app.core.projects.get_project", fake_get_project),
            mock.patch.object(raw_loader, "ensure_table"),
            mock.patch.object(raw_loader, "relax_legacy_primary_key"),
            mock.patch.object(raw_loader, "drop_stale_columns", return_value=[]),
            mock.patch.object(raw_loader, "align_column_order", return_value=False),
            mock.patch.object(raw_loader, "ensure_conflict_target"),
            mock.patch.object(raw_loader, "purge_empty_pk_rows", return_value=0),
            mock.patch.object(
                raw_loader,
                "_execute_batches",
                return_value={
                    "rows": 3,
                    "rows_inserted": 3,
                    "rows_updated": 0,
                },
            ) as batches,
            mock.patch("app.core.db.raw_engine", object()),
        ):
            result = raw_loader.upsert_dataframe(
                parse_csv(self.CSV),
                "mock_whale",
                "mock_whale",
            )

        cols = batches.call_args[0][2]
        pk = batches.call_args[0][3]
        self.assertEqual(pk, "FCoverSN")
        self.assertIn("FCoverSN", cols)
        self.assertNotIn("BCoverSN", cols)
        self.assertEqual(result["unique_key"], "FCoverSN")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["rows_inserted"], 3)


if __name__ == "__main__":
    unittest.main()
