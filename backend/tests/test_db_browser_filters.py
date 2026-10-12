"""数据浏览的筛选条件拼装测试（标准库 unittest，不连数据库）。

覆盖三件容易悄悄改坏的事：
- 筛选参数规范化：前端传 JSON 字符串，脏值/空值必须被丢掉
- 未知列必须**报错**而不是静默忽略（静默 = 导出结果"看着对"实则没筛）
- 列筛选与 ServerTime 时间范围能正确 AND 组合

运行：cd backend && .venv/Scripts/python.exe -m unittest tests.test_db_browser_filters -v
"""

from __future__ import annotations

import unittest

from app.core.db_browser import (
    _eq_clause,
    _time_clause,
    _where_clause,
    normalize_filters,
)

PG = "postgresql"
SQLITE = "sqlite"

# defect_scans 的列（次品库）
COLS = [
    "id",
    "op_id",
    "project_id",
    "project_name",
    "defect_item",
    "sn",
    "machine",
    "cavity",
    "body",
    "matched",
    "created_at",
    "ServerTime",
]


class NormalizeFiltersTest(unittest.TestCase):
    def test_none_and_empty_are_no_filter(self):
        self.assertEqual(normalize_filters(None), {})
        self.assertEqual(normalize_filters(""), {})

    def test_parses_json_string(self):
        self.assertEqual(
            normalize_filters('{"project_id": "eagle_rcvr"}'),
            {"project_id": "eagle_rcvr"},
        )

    def test_accepts_plain_dict(self):
        self.assertEqual(
            normalize_filters({"defect_item": "烟囱溢胶"}),
            {"defect_item": "烟囱溢胶"},
        )

    def test_drops_blank_values(self):
        """空串 / None 等于「不筛这一项」，不能变成 = '' 把数据筛空。"""
        self.assertEqual(
            normalize_filters({"project_id": "", "defect_item": None, "sn": "A1"}),
            {"sn": "A1"},
        )

    def test_strips_whitespace(self):
        self.assertEqual(
            normalize_filters({" project_id ": "  eagle_rcvr  "}),
            {"project_id": "eagle_rcvr"},
        )

    def test_empty_key_dropped(self):
        self.assertEqual(normalize_filters({"": "x"}), {})

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            normalize_filters("{not json")

    def test_non_object_json_raises(self):
        with self.assertRaises(ValueError):
            normalize_filters("[1, 2]")
        with self.assertRaises(ValueError):
            normalize_filters('"eagle_rcvr"')


class EqClauseTest(unittest.TestCase):
    def test_empty_filters_produce_nothing(self):
        self.assertEqual(_eq_clause(COLS, {}, PG), ([], {}))

    def test_unknown_column_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _eq_clause(COLS, {"nope": "x"}, PG)
        self.assertIn("nope", str(ctx.exception))

    def test_postgres_quotes_identifier(self):
        clauses, params = _eq_clause(COLS, {"project_id": "eagle_rcvr"}, PG)
        self.assertEqual(clauses, ['"project_id" = :f0'])
        self.assertEqual(params, {"f0": "eagle_rcvr"})

    def test_sqlite_leaves_plain_identifier(self):
        clauses, _ = _eq_clause(COLS, {"project_id": "eagle_rcvr"}, SQLITE)
        self.assertEqual(clauses, ["project_id = :f0"])

    def test_parameter_names_are_stable_and_unique(self):
        """按列名排序 → 参数名可预期，且不同列不会互相覆盖。"""
        clauses, params = _eq_clause(
            COLS, {"project_id": "eagle_rcvr", "defect_item": "粘膜"}, PG
        )
        self.assertEqual(
            clauses,
            ['"defect_item" = :f0', '"project_id" = :f1'],
        )
        self.assertEqual(params, {"f0": "粘膜", "f1": "eagle_rcvr"})

    def test_value_not_inlined_into_sql(self):
        """值必须走绑定参数，防注入：恶意值不能出现在 SQL 文本里。"""
        evil = "x'; DROP TABLE defect_scans; --"
        clauses, params = _eq_clause(COLS, {"project_id": evil}, PG)
        self.assertNotIn("DROP", " ".join(clauses))
        self.assertEqual(params["f0"], evil)


class TimeClauseTest(unittest.TestCase):
    def test_no_time_returns_no_clause(self):
        clauses, params, col = _time_clause(COLS, PG, None, None)
        self.assertEqual((clauses, params), ([], {}))
        self.assertEqual(col, "ServerTime")

    def test_missing_time_column_raises(self):
        with self.assertRaises(ValueError):
            _time_clause(["a", "b"], PG, "2026-07-02T00:00:00", None)

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            _time_clause(
                COLS, PG, "2026-07-04T00:00:00", "2026-07-02T00:00:00"
            )

    def test_single_side_allowed(self):
        clauses, params, _ = _time_clause(COLS, PG, "2026-07-02T00:00:00", None)
        self.assertEqual(len(clauses), 1)
        self.assertIn("time_from", params)
        self.assertNotIn("time_to", params)

    def test_bounds_are_inclusive(self):
        clauses, _, _ = _time_clause(
            COLS, PG, "2026-07-02T00:00:00", "2026-07-04T00:00:00"
        )
        self.assertTrue(clauses[0].endswith(">= :time_from"), clauses[0])
        self.assertTrue(clauses[1].endswith("<= :time_to"), clauses[1])


class WhereClauseTest(unittest.TestCase):
    def test_no_condition_is_empty(self):
        where, params, col = _where_clause(COLS, PG)
        self.assertEqual(where, "")
        self.assertEqual(params, {})
        self.assertEqual(col, "ServerTime")

    def test_filters_only(self):
        where, params, _ = _where_clause(
            COLS, PG, filters={"project_id": "eagle_rcvr"}
        )
        self.assertEqual(where, ' WHERE "project_id" = :f0')
        self.assertEqual(params, {"f0": "eagle_rcvr"})

    def test_time_only(self):
        where, params, _ = _where_clause(
            COLS, PG, time_from="2026-07-02T00:00:00"
        )
        self.assertTrue(where.startswith(" WHERE "))
        self.assertEqual(list(params), ["time_from"])

    def test_time_and_filters_combined_with_and(self):
        where, params, _ = _where_clause(
            COLS,
            PG,
            filters={"project_id": "eagle_rcvr", "defect_item": "烟囱溢胶"},
            time_from="2026-07-02T00:00:00",
            time_to="2026-07-04T00:00:00",
        )
        self.assertEqual(where.count(" AND "), 3)
        self.assertEqual(where.count(" WHERE "), 1)
        # 参数名是 f0/f1，列名只出现在 SQL 文本里；两者不能互相覆盖
        self.assertEqual(sorted(params), ["f0", "f1", "time_from", "time_to"])
        self.assertIn('"defect_item" = :f0', where)
        self.assertIn('"project_id" = :f1', where)
        self.assertEqual(params["f0"], "烟囱溢胶")
        self.assertEqual(params["f1"], "eagle_rcvr")

    def test_unknown_column_raises_before_hitting_db(self):
        with self.assertRaises(ValueError):
            _where_clause(COLS, PG, filters={"typo_col": "1"})

    def test_dirty_filters_do_not_add_clause(self):
        """normalize 之后的空值不应产生 = '' 或悬空的 AND。"""
        where, params, _ = _where_clause(
            COLS, PG, filters=normalize_filters({"project_id": ""})
        )
        self.assertEqual(where, "")
        self.assertEqual(params, {})


if __name__ == "__main__":
    unittest.main()
