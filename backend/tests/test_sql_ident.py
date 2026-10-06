"""app/core/sql_ident.py 的行为契约测试。

与 ``scripts/_diff_sql_ident.py`` 的分工：
- 差分脚本拿改前快照逐用例比对，证明「这次搬移没改行为」，**一次性**，依赖临时快照。
- 本文件把关键行为固化成常驻断言，不依赖任何快照，防止以后有人改坏这些函数。

这5 个函数是全项目所有表名/列名的生成入口：ident 一旦变形，
raw / dwh / ads 三层的历史表名就对不上，表现为「数据不见了」而不是报错。
所以对边界行为必须钉死。
"""

from __future__ import annotations

import unittest

from app.core.sql_ident import (
    ident,
    is_safe_sql_expression,
    q,
    table_name,
    unique_idents,
)


class IdentTest(unittest.TestCase):
    def test_keeps_chinese(self) -> None:
        """中文列名必须保留 —— ident 一转就全变 col，raw 表结构直接对不上。"""
        for name in ("模穴", "结果", "数量", "机台"):
            self.assertEqual(ident(name), name)

    def test_non_word_becomes_underscore(self) -> None:
        self.assertEqual(ident("a b"), "a_b")
        self.assertEqual(ident("a-b"), "a_b")
        self.assertEqual(ident("a.b"), "a_b")

    def test_strips_edges_and_quotes(self) -> None:
        self.assertEqual(ident("  a  "), "a")
        self.assertEqual(ident("__a__"), "a")
        self.assertEqual(ident('a"b'), "a_b")

    def test_empty_falls_back_to_col(self) -> None:
        for name in ("", "   ", "!!!", "---", '"""'):
            self.assertEqual(ident(name), "col", f"{name!r} 应回退为 col")

    def test_leading_digit_gets_prefix(self) -> None:
        """PG 标识符不能以数字开头，必须加前缀。"""
        self.assertEqual(ident("1abc"), "c_1abc")
        self.assertEqual(ident("9"), "c_9")

    def test_truncated_to_60(self) -> None:
        """PG 标识符上限 63 字节，这里留余量截到 60。"""
        self.assertEqual(len(ident("x" * 200)), 60)
        self.assertEqual(ident("x" * 200), "x" * 60)


class UniqueIdentsTest(unittest.TestCase):
    def test_preserves_order(self) -> None:
        self.assertEqual(unique_idents(["b", "a", "c"]), ["b", "a", "c"])

    def test_disambiguates_duplicates(self) -> None:
        self.assertEqual(unique_idents(["a", "a"]), ["a", "a_2"])
        self.assertEqual(unique_idents(["a", "a", "a"]), ["a", "a_2", "a_3"])

    def test_case_insensitive_dedup(self) -> None:
        """列名大小写不同但 PG 视为同一个，必须去重。"""
        self.assertEqual(unique_idents(["A", "a"]), ["A", "a_2"])

    def test_chinese_dedup(self) -> None:
        self.assertEqual(unique_idents(["模穴", "模穴"]), ["模穴", "模穴_2"])

    def test_collision_after_normalize(self) -> None:
        self.assertEqual(unique_idents(["a b", "a-b"]), ["a_b", "a_b_2"])

    def test_empty_input(self) -> None:
        self.assertEqual(unique_idents([]), [])


class QTest(unittest.TestCase):
    def test_double_quotes(self) -> None:
        self.assertEqual(q("abc"), '"abc"')

    def test_already_safe_not_reformed(self) -> None:
        """q 不该对已规范化的名字二次变形，否则 table_col 会变成 table__col。"""
        self.assertEqual(q("table_col"), '"table_col"')

    def test_unsafe_goes_through_ident(self) -> None:
        self.assertEqual(q("a b"), '"a_b"')
        self.assertEqual(q("a-b"), '"a_b"')

    def test_quote_injection_blocked(self) -> None:
        """标识符里带引号必须被清掉，否则能拼出 SQL 注入。"""
        self.assertNotIn('""', q('a"b"c'))

    def test_chinese_quoted(self) -> None:
        self.assertEqual(q("模穴"), '"模穴"')


class TableNameTest(unittest.TestCase):
    def test_prefix_wins(self) -> None:
        self.assertEqual(table_name("proj", "other"), "proj_raw")

    def test_falls_back_to_project_id(self) -> None:
        self.assertEqual(table_name("", "pid"), "pid_raw")

    def test_normalized(self) -> None:
        self.assertEqual(table_name("a b", "x"), "a_b_raw")

    def test_suffix_always_raw(self) -> None:
        self.assertTrue(table_name("z", "y").endswith("_raw"))


class SafeSqlExpressionTest(unittest.TestCase):
    def test_empty_rejected(self) -> None:
        for s in ("", "   ", None):
            self.assertFalse(is_safe_sql_expression(s), f"{s!r} 应判为不安全")

    def test_plain_expression_allowed(self) -> None:
        for s in ("a", "SUM(x)", "a + b * c", "SUM(CASE WHEN a>1 THEN 1 ELSE 0 END)"):
            self.assertTrue(is_safe_sql_expression(s), f"{s!r} 应放行")

    def test_forbidden_keywords(self) -> None:
        for s in (
            "DROP TABLE t", "delete from t", "TRUNCATE t", "INSERT INTO t VALUES(1)",
            "UPDATE t SET a=1", "ALTER TABLE t ADD c int", "CREATE TABLE t()",
            "GRANT ALL", "REVOKE ALL", "COPY t FROM '/etc/passwd'",
            "EXECUTE f()", "CALL p()", "MERGE INTO t",
        ):
            self.assertFalse(is_safe_sql_expression(s), f"{s!r} 应被拦截")

    def test_case_insensitive(self) -> None:
        self.assertFalse(is_safe_sql_expression("drop table t"))
        self.assertFalse(is_safe_sql_expression("DrOp TaBlE t"))

    def test_semicolon_rejected(self) -> None:
        """分号意味着语句拼接 —— 单条公式里出现就必须拒。"""
        self.assertFalse(is_safe_sql_expression("a; b"))
        self.assertFalse(is_safe_sql_expression("SELECT 1; DROP TABLE t"))

    def test_comment_rejected(self) -> None:
        for s in ("a -- b", "a /* b */ c", "a/*x*/", "x--"):
            self.assertFalse(is_safe_sql_expression(s), f"{s!r} 应被拦截")

    def test_keyword_as_substring_allowed(self) -> None:
        """关键字只作完整单词才拦；列名里含这些字母不该误杀。"""
        for s in ("updated_at", "created", "droplet", "modality", "replicated", "merged"):
            self.assertTrue(is_safe_sql_expression(s), f"{s!r} 不该被误杀")

    def test_chinese_expression_allowed(self) -> None:
        self.assertTrue(is_safe_sql_expression("呼叫机台机台"))


if __name__ == "__main__":
    unittest.main()
