# -*- coding: utf-8 -*-
"""Gunicorn / WSGI 入口（Docker 部署使用）"""

import atexit
import logging
import signal

from app.api import create_app
from app.config import Config
from app.database import Database
from app.transfer_service import TransferService
from main import setup_logging

config = Config()
setup_logging(config)
logger = logging.getLogger(__name__)

paths = config.get_paths()
db = Database(paths.get('database', 'data/data.db'))
transfer_service = TransferService(config, db)
transfer_service.init_on_startup()
db.cleanup_stale_incomplete_sessions(max_age_hours=48)

app = create_app(config, db, transfer_service)


def _shutdown():
    logger.info('正在关闭后台服务...')
    transfer_service.stop()
    transfer_service.stop_cleanup_scheduler()


atexit.register(_shutdown)


def _handle_signal(signum, frame):
    _shutdown()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
