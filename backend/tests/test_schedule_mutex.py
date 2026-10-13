"""定时运行与 pipeline_linkage 互斥（peer_sync）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class ScheduleMutexTests(unittest.TestCase):
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
        noop = lambda: None  # noqa: E731
        self._patches = [
            mock.patch("app.core.etl_config.MetaSession", self.Session),
            mock.patch("app.core.etl_config.init_meta_store", noop),
            mock.patch("app.core.agg_config.MetaSession", self.Session),
            mock.patch("app.core.agg_config.init_meta_store", noop),
            mock.patch("app.core.linkage_config.MetaSession", self.Session),
            mock.patch("app.core.linkage_config.init_meta_store", noop),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_etl_interval_disables_linkage(self) -> None:
        from app.core.etl_config import load_etl_config, save_etl_config
        from app.core.linkage_config import load_linkage_config, save_linkage_config

        save_linkage_config({"enabled": True}, peer_sync=False)
        self.assertTrue(load_linkage_config()["enabled"])

        save_etl_config({"is_active": True, "run_interval": 15})
        self.assertTrue(load_etl_config()["is_active"])
        self.assertFalse(load_linkage_config()["enabled"])

    def test_linkage_disables_etl_and_agg_timers(self) -> None:
        from app.core.agg_config import load_agg_config, save_agg_config
        from app.core.etl_config import load_etl_config, save_etl_config
        from app.core.linkage_config import load_linkage_config, save_linkage_config

        save_etl_config({"is_active": True}, peer_sync=False)
        save_agg_config({"is_active": True}, peer_sync=False)
        save_linkage_config({"enabled": True})

        self.assertTrue(load_linkage_config()["enabled"])
        self.assertFalse(load_etl_config()["is_active"])
        self.assertFalse(load_agg_config()["is_active"])

    def test_peer_sync_false_skips_cascade(self) -> None:
        from app.core.etl_config import load_etl_config, save_etl_config
        from app.core.linkage_config import load_linkage_config, save_linkage_config

        save_linkage_config({"enabled": True}, peer_sync=False)
        save_etl_config({"is_active": True}, peer_sync=False)
        self.assertTrue(load_etl_config()["is_active"])
        self.assertTrue(load_linkage_config()["enabled"])


if __name__ == "__main__":
    unittest.main()
