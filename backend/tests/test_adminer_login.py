"""Adminer 按页签选库：服务器映射与登录载荷。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class AdminerServerMappingTests(unittest.TestCase):
    def test_loopback_port_maps_to_docker_dns(self) -> None:
        from app.core.connections import adminer_server_for

        self.assertEqual(
            adminer_server_for({"host": "127.0.0.1", "port": 15432}, "raw"),
            "postgres-raw",
        )
        self.assertEqual(
            adminer_server_for({"host": "localhost", "port": 15433}, "dwh"),
            "postgres-dwh",
        )
        self.assertEqual(
            adminer_server_for({"host": "127.0.0.1", "port": 15434}, "defect"),
            "postgres-defect",
        )

    def test_lan_host_keeps_port(self) -> None:
        from app.core.connections import adminer_server_for

        self.assertEqual(
            adminer_server_for({"host": "192.168.2.38", "port": 15432}, "raw"),
            "192.168.2.38:15432",
        )

    def test_docker_dns_omits_default_port(self) -> None:
        from app.core.connections import adminer_server_for

        self.assertEqual(
            adminer_server_for({"host": "postgres-dwh", "port": 5432}, "dwh"),
            "postgres-dwh",
        )


class AdminerLoginPayloadTests(unittest.TestCase):
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
            mock.patch("app.core.connections.MetaSession", self.Session),
            mock.patch("app.core.connections.init_meta_store", noop),
        ]
        for p in self._patches:
            p.start()
        from app.core.connections import save_connections, save_dbweb

        save_dbweb(
            {
                "url": "http://127.0.0.1:18080",
                "sqlite_path": "/data/meta/lim_meta.sqlite",
            }
        )
        save_connections(
            {
                "raw": {
                    "host": "127.0.0.1",
                    "port": 15432,
                    "database": "lim_raw",
                    "username": "lim",
                    "password": "lim",
                },
                "dwh": {
                    "host": "127.0.0.1",
                    "port": 15433,
                    "database": "lim_dwh",
                    "username": "lim",
                    "password": "lim",
                },
                "defect": {
                    "host": "127.0.0.1",
                    "port": 15434,
                    "database": "lim_defect",
                    "username": "lim",
                    "password": "secret",
                },
            }
        )

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_meta_sqlite(self) -> None:
        from app.core.connections import adminer_login_payload

        payload = adminer_login_payload("meta")
        self.assertEqual(payload["driver"], "sqlite")
        self.assertEqual(payload["db"], "/data/meta/lim_meta.sqlite")
        self.assertEqual(payload["adminer_url"], "http://127.0.0.1:18080")

    def test_dwh_pgsql_autologin_fields(self) -> None:
        from app.core.connections import adminer_login_payload

        payload = adminer_login_payload("dwh")
        self.assertEqual(payload["driver"], "pgsql")
        self.assertEqual(payload["server"], "postgres-dwh")
        self.assertEqual(payload["db"], "lim_dwh")
        self.assertEqual(payload["username"], "lim")
        self.assertEqual(payload["password"], "lim")

    def test_unknown_target(self) -> None:
        from app.core.connections import adminer_login_payload

        with self.assertRaises(ValueError):
            adminer_login_payload("nope")


if __name__ == "__main__":
    unittest.main()
