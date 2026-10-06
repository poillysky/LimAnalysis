# -*- coding: utf-8 -*-
"""NAS工业图片自动化归档与巡机审核系统 - 主程序入口"""

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config import Config
from app.database import Database
from app.transfer_service import TransferService
from app.api import create_app


def setup_logging(config: Config):
    """配置日志"""
    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', '/data/logs/app.log')
    max_size_mb = log_config.get('max_size_mb', 50)
    backup_count = log_config.get('backup_count', 10)
    
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def main():
    """主函数"""
    config = Config()
    setup_logging(config)
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("NAS工业图片自动化归档与巡机审核系统 启动中...")
    logger.info("=" * 60)
    
    paths = config.get_paths()
    db = Database(paths.get('database', '/data/data.db'))
    
    transfer_service = TransferService(config, db)
    transfer_service.init_on_startup()
    db.cleanup_stale_incomplete_sessions(max_age_hours=48)
    
    app = create_app(config, db, transfer_service)
    
    web_config = config.get('web', {})
    host = web_config.get('host', '0.0.0.0')
    port = web_config.get('port', 5000)
    debug = web_config.get('debug', False)
    
    logger.info(f"Web服务启动: http://{host}:{port}")
    
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭...")
    finally:
        transfer_service.stop()
        transfer_service.stop_cleanup_scheduler()
        logger.info("系统已停止")


if __name__ == '__main__':
    main()
