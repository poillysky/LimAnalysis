"""字段类型推断与 SQL 强制转换的基线测试（标准库 unittest）。

这些是纯函数、无外部依赖，是整个 ETL 里最容易悄悄改坏的部分：
类型判错会让 DWH 建出错误的列类型，事后要重刷全表。
所以这里把当前行为**逐条钉死**，任何改动导致的偏移都会立刻暴露。
"""

from __future__ import annotations

import unittest

from processor.field_types import (
    ALLOWED_TYPES,
    cast_direct_expr,
    coerce_sql_to_field_type,
    guess_field_type,
    guess_field_type_from_samples,
    guess_field_types_for_table,
    normalize_field_type,
    pg_type_for_field_type,
    sql_blank_as_null,
)


class NormalizeFieldTypeTest(unittest.TestCase):
    def test_aliases_map_to_canonical(self):
        cases = {
            "string": "text",
            "STR": "text",
            "文本": "text",
            "int": "integer",
            "整数": "integer",
            "float": "decimal",
            "number": "decimal",
            "小数": "decimal",
            "百分比": "percent",
            "pct": "percent",
            "time": "datetime",
            "date": "datetime",
            "timestamp": "datetime",
            "时间": "datetime",
            "日期": "datetime",
            "bool": "boolean",
            "布尔": "boolean",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_field_type(raw), want)

    def test_canonical_passthrough(self):
        for t in sorted(ALLOWED_TYPES):
            self.assertEqual(normalize_field_type(t), t)

    def test_unknown_falls_back_to_text(self):
        for bad in ["", None, "json", "xml", "blob", "  ", "TEXT2"]:
            self.assertEqual(normalize_field_type(bad), "text", bad)

    def test_is_case_and_space_insensitive(self):
        self.assertEqual(normalize_field_type("  Decimal  "), "decimal")


class GuessByNameTest(unittest.TestCase):
    """只看列名的推断。"""

    def test_dimension_names_are_text(self):
        """线体/机台/模穴等取值可能是 '1'，但本质是文本。"""
        for name in ["线体", "产线", "机台", "工站", "模穴", "穴号", "料号",
                     "批次", "班次", "人员", "line_id", "station", "SN"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "text", name)

    def test_time_names(self):
        for name in ["ServerTime", "created_at", "_time", "ingested", "上传时间", "日期"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "datetime", name)

    def test_percent_names(self):
        for name in ["不良率", "合格率", "rate", "percent", "占比%"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "percent", name)

    def test_boolean_names(self):
        for name in ["是否OK", "判定结果", "合格", "NG标志", "pass_flag"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "boolean", name)

    def test_integer_names(self):
        for name in ["数量", "计数", "次数", "序号", "shot_count", "num"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "integer", name)

    def test_single_letter_n_is_text(self):
        """`_n$` 需要下划线前缀；裸列名 "n" 不算整数（避免误伤）。"""
        self.assertEqual(guess_field_type("n"), "text")

    def test_decimal_names(self):
        for name in ["直径", "温度", "压力", "长度", "value"]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "decimal", name)

    def test_falls_back_to_text(self):
        for name in ["备注", "remark", "foo", ""]:
            with self.subTest(name=name):
                self.assertEqual(guess_field_type(name), "text", name)


class GuessBySamplesTest(unittest.TestCase):
    """列名 + 采样值联合推断。"""

    def test_dimension_name_beats_numeric_samples(self):
        """关键规则：线体取值为 1 也不能判成整数/布尔。"""
        self.assertEqual(
            guess_field_type_from_samples("线体", ["1", "2", "1", "3"]), "text"
        )
        self.assertEqual(
            guess_field_type_from_samples("模穴", ["1", "2"]), "text"
        )

    def test_result_column_with_ok_ng_is_boolean(self):
        self.assertEqual(
            guess_field_type_from_samples("结果", ["OK", "NG", "OK"]), "boolean"
        )

    def test_defect_column_with_0_1_is_boolean(self):
        self.assertEqual(
            guess_field_type_from_samples("气泡", ["0", "1", "0"]), "boolean"
        )

    def test_single_sided_01_not_boolean_without_name_hint(self):
        """只有单边 0/1 且列名不像判定 → 不当布尔。"""
        self.assertEqual(guess_field_type_from_samples("未知列", ["1", "1", "1"]), "text")

    def test_single_sided_01_boolean_when_name_hints(self):
        """单边 1 + 列名像判定 → 布尔（点检简码 B1 需纯英文才匹配）。"""
        self.assertEqual(guess_field_type_from_samples("是否异常", ["1"]), "boolean")

    def test_chinese_inspect_code_not_boolean(self):
        """`_INSPECT_CODE_RE` 只认 B1 这类纯英文简码；中文列名不匹配 → 回退列名。"""
        self.assertEqual(guess_field_type_from_samples("点检B1", ["1", "1"]), "text")

    def test_iso_timestamps_are_datetime(self):
        vals = ["2026-10-06 12:00:00", "2026-10-06T13:30:00", "2026-10-06"]
        self.assertEqual(guess_field_type_from_samples("采集", vals), "datetime")

    def test_hms_timestamps_are_datetime(self):
        self.assertEqual(
            guess_field_type_from_samples("采集", ["12:00:00", "13:30:59"]), "datetime"
        )

    def test_percent_values(self):
        self.assertEqual(
            guess_field_type_from_samples("占比", ["1.5%", "2.5%", "0%"]), "percent"
        )

    def test_pure_01_falls_back_to_name(self):
        """双边 0/1 + 名称像计数 → 按 `_samples_look_boolean` 判布尔（现行行为）。"""
        self.assertEqual(guess_field_type_from_samples("数量", ["0", "1"]), "boolean")

    def test_single_value_01_falls_back_to_name(self):
        """单边 0/1 且列名不含判定词 → 回退列名规则，不当整数。"""
        self.assertEqual(guess_field_type_from_samples("Foo", ["1", "1", "1"]), "text")

    def test_integers(self):
        """列名 "Value" 命中 _DEC_RE 会被 decimal 抢先，这里用无特征列名验证整数分支。"""
        self.assertEqual(guess_field_type_from_samples("Value", ["1", "2", "30"]), "integer")
        self.assertEqual(guess_field_type_from_samples("Foo", ["1", "2", "30"]), "integer")

    def test_decimals(self):
        self.assertEqual(guess_field_type_from_samples("Foo", ["1.5", "2", "3.25"]), "decimal")

    def test_negative_numbers(self):
        self.assertEqual(guess_field_type_from_samples("Foo", ["-1", "-2.5"]), "decimal")

    def test_empty_and_none_samples_ignored(self):
        self.assertEqual(guess_field_type_from_samples("数量", [None, "", "  ", "5"]), "integer")

    def test_all_none_samples_falls_back_to_name(self):
        self.assertEqual(guess_field_type_from_samples("数量", [None, None]), "integer")

    def test_no_samples_falls_back_to_name(self):
        self.assertEqual(guess_field_type_from_samples("不良率", None), "percent")

    def test_mixed_text_and_number_is_text(self):
        self.assertEqual(guess_field_type_from_samples("Foo", ["1", "abc"]), "text")

    def test_text_dimension_name_wins_over_time_samples(self):
        self.assertEqual(
            guess_field_type_from_samples("上传工站", ["2026-10-06 10:00:00"]), "text"
        )


class GuessForTableTest(unittest.TestCase):
    def test_mapping_rows(self):
        cols = ["数量", "不良率"]
        rows = [{"数量": 1, "不良率": "2%"}, {"数量": 2, "不良率": "3%"}]
        self.assertEqual(
            guess_field_types_for_table(cols, rows),
            {"数量": "integer", "不良率": "percent"},
        )

    def test_sequence_rows(self):
        cols = ["数量", "备注"]
        rows = [(1, "abc"), (2, "def")]
        self.assertEqual(
            guess_field_types_for_table(cols, rows),
            {"数量": "integer", "备注": "text"},
        )

    def test_short_rows_tolerated(self):
        """缺列的短行不会抛错；a 只拿到 [1] → 单边 0/1 回退列名 → text。"""
        cols = ["a", "b", "c"]
        self.assertEqual(
            guess_field_types_for_table(cols, [(1, 2)]),
            {"a": "text", "b": "integer", "c": "text"},
        )

    def test_missing_keys_in_mapping_rows(self):
        cols = ["x", "y"]
        rows = [{"x": 1}, {"y": 2}]
        got = guess_field_types_for_table(cols, rows)
        self.assertEqual(set(got), {"x", "y"})

    def test_no_rows_returns_name_based(self):
        self.assertEqual(
            guess_field_types_for_table(["不良率", "备注"]),
            {"不良率": "percent", "备注": "text"},
        )

    def test_all_columns_present_in_output(self):
        cols = ["a", "b", "c", "d"]
        self.assertEqual(set(guess_field_types_for_table(cols, None)), set(cols))


class PgTypeMappingTest(unittest.TestCase):
    def test_all_types_mapped(self):
        cases = {
            "integer": "BIGINT",
            "decimal": "NUMERIC",
            "percent": "NUMERIC",
            "datetime": "TIMESTAMPTZ",
            "boolean": "SMALLINT",
            "text": "TEXT",
        }
        for ftype, pg in cases.items():
            with self.subTest(ftype=ftype):
                self.assertEqual(pg_type_for_field_type(ftype), pg)

    def test_aliases_normalized_first(self):
        self.assertEqual(pg_type_for_field_type("int"), "BIGINT")
        self.assertEqual(pg_type_for_field_type("百分比"), "NUMERIC")

    def test_unknown_becomes_text(self):
        self.assertEqual(pg_type_for_field_type("json"), "TEXT")


class SqlBlankAsNullTest(unittest.TestCase):
    def test_wraps_with_nullif_btrim(self):
        self.assertEqual(sql_blank_as_null('"col"'), "NULLIF(BTRIM(\"col\"), '')")

    def test_nested_expression(self):
        self.assertEqual(
            sql_blank_as_null("(a || b)::text"),
            "NULLIF(BTRIM((a || b)::text), '')",
        )


class CoerceSqlTest(unittest.TestCase):
    """生成的 SQL 片段必须保持原样 —— 改坏了会静默写错数据。"""

    def test_integer_coercion(self):
        out = coerce_sql_to_field_type("src", "integer")
        # 用「正则片段语义」断言，避免手写反斜杠层级出错：
        # 运行时输出里是单反斜杠 \d / \.
        self.assertIn("^-?\\d+(\\.0+)?$", out)
        self.assertIn("::bigint", out)
        self.assertIn("ELSE NULL END", out)

    def test_decimal_coercion(self):
        out = coerce_sql_to_field_type("src", "decimal")
        self.assertIn("::numeric", out)
        self.assertNotIn("::bigint", out)

    def test_percent_strips_percent_sign(self):
        out = coerce_sql_to_field_type("src", "percent")
        self.assertIn("REPLACE(", out)
        self.assertIn("'%', ''", out)

    def test_datetime_coercion(self):
        out = coerce_sql_to_field_type("src", "datetime")
        self.assertIn("::timestamptz", out)
        self.assertIn("NULLIF(BTRIM", out)

    def test_boolean_maps_words_to_smallint(self):
        out = coerce_sql_to_field_type("src", "boolean")
        for token in ["'1'", "'true'", "'ok'", "'合格'", "'0'", "'false'", "'ng'", "'不合格'"]:
            self.assertIn(token, out)
        self.assertIn("1::smallint", out)
        self.assertIn("0::smallint", out)

    def test_text_passthrough(self):
        self.assertEqual(
            coerce_sql_to_field_type("src", "text"), "NULLIF(BTRIM((src)::text), '')"
        )

    def test_source_is_parenthesized(self):
        out = coerce_sql_to_field_type("a + b", "integer")
        self.assertIn("(a + b)::text", out)

    def test_alias_normalized(self):
        self.assertIn("::bigint", coerce_sql_to_field_type("src", "int"))


class CastDirectExprTest(unittest.TestCase):
    def test_shape(self):
        out = cast_direct_expr("不良数", "ng", "integer")
        self.assertTrue(out.strip().startswith("NULLIF") or "CASE" in out)
        self.assertTrue(out.rstrip().endswith('AS "ng"'), out)

    def test_text_type_no_cast(self):
        out = cast_direct_expr("备注", "memo", "text")
        self.assertIn('AS "memo"', out)
        self.assertNotIn("::bigint", out)

    def test_quotes_identifiers(self):
        """ident() 会把非标识符字符转成下划线（防注入），空格不保留。"""
        out = cast_direct_expr("a b", "c d", "text")
        self.assertIn('"a_b"', out)
        self.assertIn('"c_d"', out)


if __name__ == "__main__":
    unittest.main()
