"""record_scan / record_scans 的隔离单测。

原实现直接调用 record_scans("eagle_rcvr", ...) 打真实 NAS 库，且是裸函数、
不被 unittest discover 收集 —— 既是「扫不到的死测试」，一旦改用 pytest 又会污染生产数据。

这里改为 unittest.TestCase + unittest.mock：桩掉项目/次品配置查询与真正写库的
insert_upload，只验证 record_scans 的编排逻辑（参数透传、去重、校验），
不接触任何数据库。
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.core import defect_scans


class RecordScansTest(unittest.TestCase):
    def _patch_env(self):
        """桩掉外部依赖：项目存在、次品项在配置内、写库动作被替换。"""
        return (
            mock.patch.object(
                defect_scans,
                "get_project",
                return_value={"project_id": "eagle_rcvr", "enabled": True},
            ),
            mock.patch.object(
                defect_scans,
                "list_defect_options",
                return_value=[{"key": "烟囱溢胶"}],
            ),
            mock.patch.object(
                defect_scans,
                "insert_upload",
                return_value={"count": 0, "op": {}},
            ),
        )

    def test_record_scans_passes_through_cleaned_sns(self) -> None:
        p_project, p_items, p_insert = self._patch_env()
        with p_project, p_items, p_insert as insert:
            insert.return_value = {
                "count": 2,
                "op": {"project_id": "eagle_rcvr", "defect_item": "烟囱溢胶"},
            }
            result = defect_scans.record_scans(
                "eagle_rcvr", "烟囱溢胶", ["SN_001", "SN_002"]
            )
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["op"]["project_id"], "eagle_rcvr")
        self.assertEqual(result["op"]["defect_item"], "烟囱溢胶")
        # 确认透传给 insert_upload 的 sns 已去重
        _, kwargs = insert.call_args
        self.assertEqual(kwargs["sns"], ["SN_001", "SN_002"])
        self.assertEqual(kwargs["method"], "scan")
        self.assertTrue(insert.called)

    def test_record_scans_dedupes_sns(self) -> None:
        p_project, p_items, p_insert = self._patch_env()
        with p_project, p_items, p_insert as insert:
            defect_scans.record_scans(
                "eagle_rcvr", "烟囱溢胶", ["SN_001", "SN_001", "SN_002"]
            )
        _, kwargs = insert.call_args
        self.assertEqual(kwargs["sns"], ["SN_001", "SN_002"])

    def test_record_scans_rejects_unknown_defect_item(self) -> None:
        with (
            mock.patch.object(
                defect_scans,
                "get_project",
                return_value={"project_id": "eagle_rcvr", "enabled": True},
            ),
            mock.patch.object(
                defect_scans,
                "list_defect_options",
                return_value=[{"key": "烟囱溢胶"}],
            ),
            mock.patch.object(defect_scans, "insert_upload") as insert,self.assertRaises(ValueError)
        ):
            defect_scans.record_scans("eagle_rcvr", "不存在的次品项", ["SN_001"])
        self.assertFalse(insert.called)

    def test_record_scans_rejects_empty_sns(self) -> None:
        p_project, p_items, p_insert = self._patch_env()
        with p_project, p_items, p_insert as insert, self.assertRaises(ValueError):
            defect_scans.record_scans("eagle_rcvr", "烟囱溢胶", [])
        self.assertFalse(insert.called)


if __name__ == "__main__":
    unittest.main()
