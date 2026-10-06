"""SQL 源表时间窗改写的行为测试（标准库 unittest）。

重点验证「定位失败不再静默」：旧实现 `return sql` 让增量悄悄变全量，
现在必须打 warning（strict=False）或抛错（strict=True）。
"""

from __future__ import annotations

import logging
import unittest

from processor.sql_rewrite import SourceRewriteError, safe_ident, wrap_source_time_window


def _rewrite(sql, *, table="raw_tbl", col="ServerTime", pred=None, strict=False, ctx="test"):
    return wrap_source_time_window(
        sql,
        table,
        col,
        pred or f'"{col}" >= NOW()',
        quoted_source=f'"{table}"',
        quoted_column=f'"{col}"',
        context=ctx,
        strict=strict,
    )


class RewriteSuccessTest(unittest.TestCase):
    def test_simple_select_is_wrapped(self):
        out = _rewrite('SELECT a, b FROM "raw_tbl" WHERE a > 1')
        self.assertIn(
            'FROM (SELECT * FROM "raw_tbl" WHERE "ServerTime" >= NOW()) AS "raw_tbl"',
            out,
        )
        self.assertIn("a > 1", out, "原有 WHERE 必须保留")
        self.assertTrue(out.startswith("SELECT a, b "))

    def test_multiline_sql_is_wrapped(self):
        out = _rewrite('SELECT a\nFROM "raw_tbl"\nGROUP BY a')
        self.assertIn("AS \"raw_tbl\"", out)
        self.assertIn("GROUP BY a", out)

    def test_rfind_picks_last_from_clause(self):
        """子查询在前、主表在后时，应改写主表那一处。"""
        out = _rewrite(
            'SELECT * FROM (SELECT x FROM "other") t JOIN "raw_tbl" r ON t.x = r.x'
        )
        self.assertIn(
            'JOIN (SELECT * FROM "raw_tbl" WHERE "ServerTime" >= NOW()) AS "raw_tbl" r',
            out,
        )
        self.assertEqual(out.count("AS \"raw_tbl\""), 1)
        self.assertIn('FROM (SELECT x FROM "other") t', out, "子查询不应被改写")

    def test_explicit_join_keyword_form(self):
        out = _rewrite('SELECT * FROM "raw_tbl" r JOIN "other" o ON r.id = o.id')
        self.assertIn(
            'FROM (SELECT * FROM "raw_tbl" WHERE "ServerTime" >= NOW()) AS "raw_tbl" r',
            out,
        )

    def test_alias_preserved_on_from(self):
        out = _rewrite('SELECT r.a FROM "raw_tbl" r WHERE r.a > 1')
        self.assertIn('AS "raw_tbl" r WHERE r.a > 1', out)

    def test_alias_not_swallowed_for_keyword(self):
        """"FROM t WHERE" 里的 WHERE 不能被当成别名。"""
        out = _rewrite('SELECT a FROM "raw_tbl" WHERE a > 1')
        self.assertIn('AS "raw_tbl" WHERE a > 1', out)

    def test_join_with_alias_preserved(self):
        out = _rewrite('SELECT * FROM "other" o JOIN "raw_tbl" r ON o.id = r.id')
        self.assertIn(
            'JOIN (SELECT * FROM "raw_tbl" WHERE "ServerTime" >= NOW()) AS "raw_tbl" r',
            out,
        )
        self.assertIn('FROM "other" o', out)


class RewriteFailureTest(unittest.TestCase):
    """定位失败 —— 旧实现静默返回，这里要求必须可见。"""

    def test_missing_source_logs_warning(self):
        sql = 'SELECT a FROM "some_other_table"'
        with self.assertLogs("processor.sql_rewrite", level="WARNING") as cm:
            out = _rewrite(sql)
        self.assertEqual(out, sql, "定位失败时保持原 SQL（不破坏执行）")
        self.assertTrue(
            any("全量" in m for m in cm.output),
            f"必须告警提示退化为全量，实际: {cm.output}",
        )

    def test_missing_source_raises_when_strict(self):
        sql = 'SELECT a FROM "some_other_table"'
        with self.assertRaises(SourceRewriteError) as ctx:
            _rewrite(sql, strict=True)
        self.assertIn("全量", str(ctx.exception))

    def test_warning_mentions_table_name(self):
        """SQL 里没有目标表 → 告警里要能看到是哪个表没找到。"""
        with self.assertLogs("processor.sql_rewrite", level="WARNING") as cm:
            _rewrite('SELECT a FROM "other_tbl"', table="wanted_tbl")
        self.assertTrue(
            any("wanted_tbl" in m for m in cm.output),
            f"告警需指明缺失的表名，实际: {cm.output}",
        )

    def test_warning_mentions_context(self):
        with self.assertLogs("processor.sql_rewrite", level="WARNING") as cm:
            _rewrite('SELECT a FROM "nope"', ctx="ETL 增量清洗")
        self.assertTrue(any("ETL 增量清洗" in m for m in cm.output), cm.output)

    def test_lowercase_from_not_matched(self):
        """大小写不同的 FROM 定位不到 → 必须告警而不是静默。"""
        with self.assertLogs("processor.sql_rewrite", level="WARNING"):
            out = _rewrite('SELECT a from "other"')
        self.assertIn('from "other"', out)


class SafeIdentTest(unittest.TestCase):
    def test_accepts_plain_identifier(self):
        self.assertEqual(safe_ident("ServerTime"), '"ServerTime"')

    def test_rejects_quote_injection(self):
        for bad in ['a"b', "a'; DROP TABLE x; --", "1abc", "", "a-b", "a b"]:
            with self.assertRaises(ValueError, msg=bad):
                safe_ident(bad)


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
