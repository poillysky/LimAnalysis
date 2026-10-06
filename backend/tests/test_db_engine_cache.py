"""refresh_pg_engines 的 TTL 节流语义测试（标准库 unittest，零额外依赖）。

不连真实 Postgres：替换 create_engine / load_connections / build_pg_url，
只验证「什么时候真的重建」这个决策逻辑。

运行：cd backend && .venv/Scripts/python.exe -m unittest tests.test_db_engine_cache -v
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.core import db
import app.core.connections as conn_mod


class _FakeEngine:
    def __init__(self, url: str) -> None:
        self.url = url
        self.disposed = 0

    def dispose(self) -> None:
        self.disposed += 1


class EngineCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.created: list[_FakeEngine] = []
        self.url = "postgresql://u:p@h:5432/d"

        def fake_create_engine(url, **kwargs):
            eng = _FakeEngine(url)
            self.created.append(eng)
            return eng

        def fake_load_connections():
            return {"raw": self.url, "dwh": self.url, "defect": self.url}

        patches = [
            mock.patch.object(db, "create_engine", fake_create_engine),
            mock.patch.object(conn_mod, "load_connections", fake_load_connections),
            mock.patch.object(conn_mod, "build_pg_url", lambda c: c),
            mock.patch.object(db, "_pg_engine_key", None),
            mock.patch.object(db, "_pg_engine_at", 0.0),
            mock.patch.object(db, "_PG_ENGINE_TTL", 30.0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @property
    def n(self) -> int:
        return len(self.created)

    def test_first_call_rebuilds(self):
        self.assertTrue(db.refresh_pg_engines())
        self.assertEqual(self.n, 3)

    def test_second_call_within_ttl_is_cached(self):
        db.refresh_pg_engines()
        before = self.n
        self.assertFalse(db.refresh_pg_engines())
        self.assertEqual(self.n, before, "TTL 内不应重建 engine")

    def test_repeated_calls_stay_cached(self):
        """旧实现下 50 次调用会建 150 个 engine；现在只应建 3 个。"""
        for _ in range(50):
            db.refresh_pg_engines()
        self.assertEqual(self.n, 3)

    def test_force_rebuilds_even_within_ttl(self):
        db.refresh_pg_engines()
        before = self.n
        self.assertTrue(db.refresh_pg_engines(force=True))
        self.assertEqual(self.n, before + 3)

    def test_url_change_rebuilds_immediately(self):
        db.refresh_pg_engines()
        before = self.n
        self.url = "postgresql://u:p@other:5433/d"
        self.assertTrue(db.refresh_pg_engines())
        self.assertEqual(self.n, before + 3, "连接串变了必须立刻重建")

    def test_ttl_expiry_rebuilds(self):
        db.refresh_pg_engines()
        before = self.n
        db._pg_engine_at = db._pg_engine_at - 31.0
        self.assertTrue(db.refresh_pg_engines())
        self.assertEqual(self.n, before + 3)

    def test_old_engines_disposed_on_rebuild(self):
        db.refresh_pg_engines()
        first = list(self.created)
        self.url = "postgresql://u:p@h2:5432/d"
        db.refresh_pg_engines()
        for eng in first:
            self.assertEqual(eng.disposed, 1, "重建后旧 engine 必须 dispose")

    def test_cache_state_updated_after_rebuild(self):
        db.refresh_pg_engines()
        self.assertEqual(db._pg_engine_key, (self.url, self.url, self.url))
        self.assertGreater(db._pg_engine_at, 0)

    def test_sessions_rebound_to_new_engines(self):
        db.refresh_pg_engines()
        self.assertIs(db.RawSession.kw["bind"], db.raw_engine)
        self.assertIs(db.DwhSession.kw["bind"], db.dwh_engine)
        self.assertIs(db.DefectSession.kw["bind"], db.defect_engine)


if __name__ == "__main__":
    unittest.main()
