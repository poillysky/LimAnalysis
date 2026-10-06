"""requeue_stale_running 的归属判定测试。

覆盖的 bug：`collector/jobs.py` 的 requeue_stale_running 原实现无条件把所有
running 任务标 failed，注释却写「本进程负责的残留」。多 worker 并存时（如
README 里的 `collector.worker --only crawl` 与全量 worker 同跑），任一 worker
重启会把别人正在执行的任务误杀。

跑法：cd backend && .venv/Scripts/python.exe -m unittest tests.test_jobs_stale -v

隔离方式（踩过坑才这么写）：
不用「删 sys.modules 再改 META_SQLITE_PATH」那套。meta_engine 是模块级
create_engine 出来的，改环境变量必须重新 import 才能生效；而重新 import
`app.core.db` 会把别的测试（test_db_engine_cache 用 mock.patch 打在这个模块
对象上）的 patch 一并失效 —— 表现为 3 个与本文件无关的失败。
改为**每个用例自建 engine + 直接 patch collector.jobs.MetaSession**：
既不碰全局模块缓存，也不用动环境变量。
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class _JobTestBase(unittest.TestCase):
    """给每个用例一个独立的内存 SQLite + 自己的 sessionmaker。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "meta.sqlite3"
        # 用独立文件而非 :memory: —— init_meta_store 走的是 engine 级连接池，
        # 内存库在多连接下会各自看到不同 schema。
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        from app.core.meta_models import MetaJob

        # 建表：直接用本用例的 engine。刻意**不**调 init_meta_store() ——
        # 它会连全局 meta_engine 绑定的库（仓库里真实的 data/meta/lim_meta.sqlite）。
        MetaJob.__table__.create(self.engine)
        self.MetaJob = MetaJob

        # 把 collector.jobs 依赖的两个全局入口指向本用例的库。
        # 只 patch 这两个名字，不动 app.core.db 的模块状态（见模块 docstring 的踩坑记录）。
        for target, repl in (
            ("collector.jobs.MetaSession", self.session_factory),
            ("collector.jobs.init_meta_store", lambda: None),
        ):
            p = mock.patch(target, repl)
            p.start()
            self.addCleanup(p.stop)

        self.addCleanup(self.engine.dispose)
        self.addCleanup(lambda: shutil.rmtree(self._tmp.name, ignore_errors=True))

    def _add_jobs(self, rows: list[dict]) -> None:
        db = self.session_factory()
        try:
            for r in rows:
                db.add(self.MetaJob(**r))
            db.commit()
        finally:
            db.close()

    def _row(self, job_id: int):
        db = self.session_factory()
        try:
            return db.get(self.MetaJob, job_id)
        finally:
            db.close()

    def _status(self, job_id: int) -> str:
        r = self._row(job_id)
        return r.status if r else "<missing>"


class StaleRequeueTest(_JobTestBase):
    """多 worker 并存时，回收只应命中本进程启动前就已在 running 的任务。"""

    BOOT = "2026-10-06 10:00:00"

    def setUp(self) -> None:
        super().setUp()
        # 场景：A 在 10:00:00 启动。A 自己有一条 09:50 的残留（该回收）；
        # B 在 A 启动后才领到 10:00:05 的任务（绝不能动）。
        self._add_jobs(
            [
                {"id": 1, "job_type": "sfc_crawl", "status": "running",
                     "started_at": "2026-10-06 09:50:00", "message": "running"},
                {"id": 2, "job_type": "sfc_crawl", "status": "running",
                     "started_at": "2026-10-06 10:00:05", "message": "running"},
                {"id": 3, "job_type": "sfc_crawl", "status": "running",
                     "started_at": "", "message": "running"},
                {"id": 4, "job_type": "sfc_crawl", "status": "queued",
                     "started_at": "", "message": ""},
                {"id": 5, "job_type": "sfc_upload", "status": "running",
                     "started_at": "2026-10-06 09:40:00", "message": "running"},
            ]
        )

    def _requeue(self, **kw) -> int:
        from collector.jobs import requeue_stale_running

        kw.setdefault("job_types", ("sfc_crawl",))
        kw.setdefault("started_before", self.BOOT)
        return requeue_stale_running("worker restarted", **kw)

    def test_only_reclaims_own_residue(self) -> None:
        """核心用例：A 重启只回收自己的残留，B 正在跑的必须活着。"""
        n = self._requeue()
        self.assertEqual(n, 2, "应只回收 id=1（本进程残留）和 id=3（started_at 空）")
        self.assertEqual(self._status(1), "failed", "A 自己的残留应被回收")
        self.assertEqual(self._status(3), "failed", "started_at 为空的异常 running 应被回收")
        self.assertEqual(self._status(2), "running", "B 正在跑的任务绝不能被误杀")
        self.assertEqual(self._status(4), "queued", "queued 不受影响")
        self.assertEqual(self._status(5), "running", "类型不匹配的任务不受影响")

    def test_preserves_message_and_sets_ended(self) -> None:
        """回收要写 message 与 ended_at，前端才看得到失败原因。"""
        self._requeue()
        row = self._row(1)
        self.assertEqual(row.message, "worker restarted")
        self.assertTrue(row.ended_at, "ended_at 必须写入")

    def test_boundary_equal_timestamp(self) -> None:
        """started_at 恰好等于启动时刻也要回收（用 <= 而非 <）。

        场景：worker 在 claim 任务的同一秒崩溃重启，残留的 started_at 与新进程
        启动时刻字符串完全相同。用 < 会漏掉，任务永久卡在 running。
        """
        n = self._requeue(started_before="2026-10-06 09:50:00")
        self.assertEqual(n, 2, "边界等值必须算作残留，否则任务永久占坑")
        self.assertEqual(self._status(1), "failed")

    def test_no_started_before_keeps_legacy_behavior(self) -> None:
        """不传 started_before 时退化为旧行为（全收），不破坏既有调用契约。"""
        n = self._requeue(started_before=None)
        self.assertEqual(n, 3, "旧行为：所有 running 的 crawl 都被回收")

    def test_no_types_reclaims_across_types_before_boot(self) -> None:
        """job_types=None 时按时间基准跨类型回收。"""
        n = self._requeue(job_types=None)
        self.assertEqual(n, 3, "id=1,3（crawl）+ id=5（upload，早于基准）")

    def test_is_idempotent(self) -> None:
        """重复调用不再改写：已 failed 的已不在 running 集合里。"""
        from collector.jobs import requeue_stale_running

        first = self._requeue()
        second = requeue_stale_running("y", job_types=("sfc_crawl",), started_before=self.BOOT)
        self.assertEqual(first, 2)
        self.assertEqual(second, 0, "第二次不该再回收任何东西")
        self.assertEqual(self._row(1).message, "worker restarted", "message 不该被二次调用覆盖")

    def test_now_str_matches_started_at_format(self) -> None:
        """now_str() 必须与写入 started_at 的格式一致，否则字符串比较会错。"""
        from collector.jobs import now_str

        self.assertRegex(now_str(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        # 同格式才能让 "10:00:05" > "10:00:00" 这种字典序比较成立
        self.assertTrue("2026-10-06 10:00:05" > "2026-10-06 10:00:00")


class ClaimNextJobTest(_JobTestBase):
    """claim 必须写 started_at —— 残留回收的正确性依赖这个字段。"""

    def test_claim_marks_running_with_started_at(self) -> None:
        from collector.jobs import claim_next_job

        self._add_jobs([{"id": 1, "job_type": "sfc_crawl", "status": "queued", "message": ""}])
        got = claim_next_job(("sfc_crawl",))
        self.assertIsNotNone(got)
        self.assertEqual(got["status"], "running")
        self.assertTrue(got["started_at"], "claim 必须写 started_at，否则残留回收无从判定")

    def test_claim_returns_none_when_empty(self) -> None:
        from collector.jobs import claim_next_job

        self.assertIsNone(claim_next_job(("sfc_crawl",)))


if __name__ == "__main__":
    unittest.main()
