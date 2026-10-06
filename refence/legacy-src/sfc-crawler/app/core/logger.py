"""
日志配置模块
"""
import logging
import sys
from pathlib import Path

from app.settings import settings


# 统一的日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _create_console_handler() -> logging.StreamHandler:
    """创建控制台日志处理器"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def _create_file_handler(log_dir: Path, filename: str = "app.log") -> logging.FileHandler:
    """创建文件日志处理器"""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / filename, encoding="utf-8")
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def setup_logger(name: str = "sfc-crawler", log_level: int = logging.INFO) -> logging.Logger:
    """配置日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 添加控制台输出
    logger.addHandler(_create_console_handler())

    # 添加文件输出
    log_dir = Path(__file__).parent.parent.parent / "data" / "logs"
    logger.addHandler(_create_file_handler(log_dir))

    return logger


def setup_root_logger():
    """配置根日志记录器，让所有子模块的日志都能输出"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 避免重复添加 handler
    if root_logger.handlers:
        return
    
    # 添加控制台输出
    root_logger.addHandler(_create_console_handler())
    
    # 添加文件输出
    log_dir = Path(__file__).parent.parent.parent / "data" / "logs"
    root_logger.addHandler(_create_file_handler(log_dir))


# 配置根日志记录器（让所有模块的日志都能输出）
setup_root_logger()

# 全局日志实例
logger = setup_logger()
