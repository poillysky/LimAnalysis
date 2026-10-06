"""ETL/聚合 SQL 生成与数据转换的基线测试（标准库 unittest）。

覆盖三块最容易悄悄改坏、又最难靠肉眼发现的纯逻辑：
- 公式里的字段引用规范化（改错 → SQL 引用不存在的列）
- COPY 单元类型转换（改错 → 数据静默变形，如 bool 变 "True"）
- 时间分桶表达式
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from processor.executor import _as_copy_cell, _strip_sql_comments
from processor.sql_generator import process_formula, time_bucket_expr


class StripSqlCommentsTest(unittest.TestCase):
    def test_removes_full_line_comments(self):
        sql = "-- 这是注释\nSELECT a\n-- 另一行注释\nFROM t"
        self.assertEqual(_strip_sql_comments(sql), "SELECT a\nFROM t")

    def test_keeps_inline_comment_text(self):
        """只剥离整行注释；行尾 -- 保留（Postgres 本身会当注释）。"""
        sql = "SELECT a -- 尾部\nFROM t"
        self.assertEqual(_strip_sql_comments(sql), sql)

    def test_keeps_string_literals_containing_dashes(self):
        sql = "SELECT '--not a comment' AS x"
        self.assertEqual(_strip_sql_comments(sql), sql)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(_strip_sql_comments("\n\n  SELECT 1  \n\n"), "SELECT 1")

    def test_empty_input(self):
        self.assertEqual(_strip_sql_comments(""), "")
        self.assertEqual(_strip_sql_comments("-- only comment"), "")

    def test_indented_comment_line_removed(self):
        sql = "   -- 缩进注释\nSELECT 1"
        self.assertEqual(_strip_sql_comments(sql), "SELECT 1")


class ProcessFormulaTest(unittest.TestCase):
    def test_square_brackets_become_quoted_idents(self):
        self.assertEqual(process_formula("[数量]"), '"数量"')

    def test_backticks_become_quoted_idents(self):
        self.assertEqual(process_formula("`数量`"), '"数量"')

    def test_cjk_brackets_converted(self):
        self.assertEqual(process_formula("【数量】"), '"数量"')

    def test_mixed_notation(self):
        self.assertEqual(
            process_formula("[a] + `b` + 【c】"), '"a" + "b" + "c"'
        )

    def test_leaves_bare_identifiers_alone(self):
        self.assertEqual(process_formula("count(*) + 1"), "count(*) + 1")

    def test_strips_whitespace(self):
        self.assertEqual(process_formula("  [a]  "), '"a"')

    def test_sanitizes_dangerous_field_names(self):
        """字段名带引号/分号时必须被 ident() 压成安全标识符。"""
        out = process_formula('[a"; DROP TABLE x; --]')
        self.assertNotIn("DROP TABLE x; --", out.replace('"', "").replace(" ", " "))
        self.assertIn("DROP", out)  # 词还在，但已被包进引号内，不是可执行 SQL

    def test_empty_and_none(self):
        self.assertEqual(process_formula(""), "")
        self.assertEqual(process_formula(None), "")

    def test_unclosed_bracket_left_alone(self):
        self.assertEqual(process_formula("[abc"), "[abc")


class TimeBucketExprTest(unittest.TestCase):
    def test_known_granularities(self):
        """_GRAIN_TRUNC 只支持 hour/day/week/month 四种。"""
        cases = {
            "hour": "date_trunc('hour', \"ServerTime\")",
            "day": "date_trunc('day', \"ServerTime\")",
            "week": "date_trunc('week', \"ServerTime\")",
            "month": "date_trunc('month', \"ServerTime\")",
        }
        for grain, want in cases.items():
            with self.subTest(grain=grain):
                self.assertEqual(time_bucket_expr("ServerTime", grain), want)

    def test_minute_not_supported_falls_back_to_hour(self):
        """minute 不在白名单 → 回退 hour（不生成非法 date_trunc）。"""
        self.assertEqual(
            time_bucket_expr("ServerTime", "minute"), "date_trunc('hour', \"ServerTime\")"
        )

    def test_unknown_granularity_falls_back_to_hour(self):
        self.assertEqual(
            time_bucket_expr("ServerTime", "fortnight"), "date_trunc('hour', \"ServerTime\")"
        )

    def test_case_insensitive_and_whitespace(self):
        self.assertEqual(time_bucket_expr("t", " DAY "), "date_trunc('day', \"t\")")

    def test_none_granularity_defaults_hour(self):
        self.assertEqual(time_bucket_expr("t", None), "date_trunc('hour', \"t\")")

    def test_field_name_is_quoted(self):
        self.assertEqual(time_bucket_expr("my col", "hour"), "date_trunc('hour', \"my_col\")")


class AsCopyCellTest(unittest.TestCase):
    """COPY 单元类型转换 —— 改错会让数据静默变形。"""

    def test_none_stays_none(self):
        self.assertIsNone(_as_copy_cell(None))

    def test_bool_becomes_int(self):
        """bool 必须转 0/1，不能变成 'True'/'False' 字符串。"""
        self.assertEqual(_as_copy_cell(True), 1)
        self.assertEqual(_as_copy_cell(False), 0)
        self.assertNotIsInstance(_as_copy_cell(True), bool)

    def test_numbers_keep_native_type(self):
        self.assertEqual(_as_copy_cell(5), 5)
        self.assertEqual(_as_copy_cell(5.5), 5.5)
        self.assertEqual(_as_copy_cell(Decimal("1.25")), Decimal("1.25"))

    def test_temporal_keeps_native_type(self):
        d = datetime(2026, 10, 6, 12, 0, 0)
        self.assertEqual(_as_copy_cell(d), d)
        self.assertEqual(_as_copy_cell(date(2026, 10, 6)), date(2026, 10, 6))

    def test_string_passthrough(self):
        self.assertEqual(_as_copy_cell("abc"), "abc")
        self.assertEqual(_as_copy_cell(""), "")

    def test_bytes_decoded_as_utf8(self):
        self.assertEqual(_as_copy_cell("不良".encode("utf-8")), "不良")

    def test_invalid_utf8_replaced_not_raised(self):
        self.assertIsInstance(_as_copy_cell(b"\xff\xfe"), str)

    def test_uuid_becomes_str(self):
        u = UUID("12345678-1234-5678-1234-567812345678")
        self.assertEqual(_as_copy_cell(u), str(u))

    def test_unknown_type_stringified(self):
        class Weird:
            def __str__(self):
                return "weird"

        self.assertEqual(_as_copy_cell(Weird()), "weird")

    def test_int_like_float_stays_float(self):
        self.assertIsInstance(_as_copy_cell(1.0), float)


if __name__ == "__main__":
    unittest.main()
