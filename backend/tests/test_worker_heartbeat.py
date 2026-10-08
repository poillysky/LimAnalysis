"""Worker 心跳：写入后 alive；过期后 not alive。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class WorkerHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "meta.sqlite3"
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        from app.core.meta_models import MetaBase

        MetaBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self._patches = [
            mock.patch("app.core.worker_heartbeat.MetaSession", self.Session),
            mock.patch("app.core.worker_heartbeat.init_meta_store", lambda: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_touch_then_alive(self) -> None:
        from app.core.worker_heartbeat import touch_worker_heartbeat, worker_heartbeat_status

        touch_worker_heartbeat("collector", force=True)
        touch_worker_heartbeat("agg", force=True)
        status = worker_heartbeat_status(stale_seconds=45)
        self.assertTrue(status["collector"]["alive"])
        self.assertTrue(status["agg"]["alive"])

    def test_stale_not_alive(self) -> None:
        from app.core.meta_models import MetaSetting
        from app.core.worker_heartbeat import WORKER_HEARTBEAT_KEY, worker_heartbeat_status

        old = (datetime.now() - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        db = self.Session()
        try:
            db.add(
                MetaSetting(
                    key=WORKER_HEARTBEAT_KEY,
                    value={"collector": {"at": old, "pid": 1}, "agg": {"at": old, "pid": 2}},
                )
            )
            db.commit()
        finally:
            db.close()
        status = worker_heartbeat_status(stale_seconds=45)
        self.assertFalse(status["collector"]["alive"])
        self.assertFalse(status["agg"]["alive"])


if __name__ == "__main__":
    unittest.main()
