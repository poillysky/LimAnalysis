"""A2B 客户端心跳：upsert、stale、槽位合并。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class A2bHeartbeatTests(unittest.TestCase):
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
            mock.patch("app.core.a2b_heartbeat.MetaSession", self.Session),
            mock.patch("app.core.a2b_heartbeat.init_meta_store", lambda: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_upsert_camel_case(self) -> None:
        from app.core.a2b_heartbeat import list_heartbeats, upsert_heartbeat

        row = upsert_heartbeat(
            {
                "clientId": "D6",
                "deviceAlias": "D6",
                "mode": "mold",
                "machine": "D6",
                "clientStatus": "监控中",
                "paused": False,
                "okCount": 3,
                "failCount": 1,
                "hostName": "PC-A",
                "clientVersion": "1.0.0",
                "source": r"C:\A2B\Source",
                "target": r"\\NAS\D6",
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["client_id"], "D6")
        self.assertEqual(row["machine"], "D6")
        self.assertEqual(row["client_status"], "监控中")
        self.assertEqual(row["ok_count"], 3)
        self.assertTrue(row["last_seen_at"])

        again = upsert_heartbeat(
            {
                "clientId": "D6",
                "mode": "mold",
                "machine": "D6",
                "clientStatus": "已暂停",
                "paused": True,
                "okCount": 5,
            }
        )
        assert again is not None
        self.assertEqual(again["client_status"], "已暂停")
        self.assertTrue(again["paused"])
        self.assertEqual(again["ok_count"], 5)
        self.assertEqual(len(list_heartbeats(mode="mold")), 1)

    def test_machine_fallback_to_alias(self) -> None:
        from app.core.a2b_heartbeat import upsert_heartbeat

        row = upsert_heartbeat({"deviceAlias": "N3", "mode": "mold", "clientStatus": "监控中"})
        assert row is not None
        self.assertEqual(row["client_id"], "N3")
        self.assertEqual(row["machine"], "N3")

    def test_stale_offline(self) -> None:
        from app.core.a2b_heartbeat import build_a2b_status, upsert_heartbeat
        from app.core.meta_models import MetaA2bClientHeartbeat

        upsert_heartbeat(
            {
                "clientId": "D1",
                "mode": "mold",
                "machine": "D1",
                "clientStatus": "监控中",
            }
        )
        old = (datetime.now() - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        db = self.Session()
        try:
            row = db.get(MetaA2bClientHeartbeat, "D1")
            assert row is not None
            row.last_seen_at = old
            db.commit()
        finally:
            db.close()

        status = build_a2b_status(
            mode="mold",
            stale_seconds=90,
            projects=[
                {
                    "project_id": "p1",
                    "display_name": "Proj",
                    "enabled": True,
                    "machines": ["D1"],
                    "appearance_machines": [],
                }
            ],
        )
        self.assertEqual(status["slots"][0]["presence"], "offline")
        self.assertFalse(status["slots"][0]["online"])

    def test_merge_mold_slots(self) -> None:
        from app.core.a2b_heartbeat import build_a2b_status, upsert_heartbeat

        upsert_heartbeat(
            {
                "clientId": "D2",
                "mode": "mold",
                "machine": "D2",
                "clientStatus": "同步中",
                "okCount": 2,
            }
        )
        # 未登记机台
        upsert_heartbeat(
            {
                "clientId": "Z9",
                "mode": "mold",
                "machine": "Z9",
                "clientStatus": "监控中",
            }
        )

        status = build_a2b_status(
            mode="mold",
            stale_seconds=90,
            projects=[
                {
                    "project_id": "eel",
                    "display_name": "Eelspkr",
                    "enabled": True,
                    "machines": ["D1", "D2"],
                    "appearance_machines": [],
                },
                {
                    "project_id": "off",
                    "display_name": "Off",
                    "enabled": False,
                    "machines": ["D3"],
                    "appearance_machines": [],
                },
            ],
        )
        self.assertEqual(status["summary"]["total_slots"], 2)
        by_machine = {s["machine"]: s for s in status["slots"]}
        self.assertEqual(by_machine["D1"]["presence"], "never")
        self.assertEqual(by_machine["D2"]["presence"], "online")
        self.assertEqual(by_machine["D2"]["client_status"], "同步中")
        self.assertEqual(len(status["unregistered"]), 1)
        self.assertEqual(status["unregistered"][0]["machine"], "Z9")

    def test_merge_appearance_slots(self) -> None:
        from app.core.a2b_heartbeat import build_a2b_status, upsert_heartbeat

        upsert_heartbeat(
            {
                "clientId": "Eelspkr-GV-0701-2",
                "deviceAlias": "Eelspkr-GV-0701-2",
                "mode": "appearance",
                "project": "Eelspkr",
                "machine": "GV-0701",
                "station": "2",
                "clientStatus": "已暂停",
                "paused": True,
            }
        )

        status = build_a2b_status(
            mode="appearance",
            stale_seconds=90,
            projects=[
                {
                    "project_id": "eel",
                    "display_name": "Eelspkr",
                    "prefix": "eel",
                    "enabled": True,
                    "machines": [],
                    "appearance_machines": ["GV-0701"],
                }
            ],
        )
        self.assertEqual(status["summary"]["total_slots"], 2)  # 工站 1/2
        by_station = {s["station"]: s for s in status["slots"]}
        self.assertEqual(by_station["1"]["presence"], "never")
        self.assertEqual(by_station["2"]["presence"], "online")
        self.assertEqual(by_station["2"]["client_status"], "已暂停")
        self.assertTrue(by_station["2"]["paused"])
        self.assertEqual(status["summary"]["unregistered"], 0)


if __name__ == "__main__":
    unittest.main()
