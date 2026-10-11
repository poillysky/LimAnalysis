"""统一日志配置。

项目统一使用标准库 logging（不引入 Loguru），由本模块集中初始化：
- 统一格式：时间 级别 模块名 消息
- 统一级别：默认 INFO，可用环境变量 LIM_LOG_LEVEL 覆盖
- 幂等：重复调用只生效一次，避免 worker 重复 basicConfig

用法：进程入口（API / 采集 Worker / 聚合 Worker）启动时调用 setup_logging()。
"""

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_configured = False

# 第三方库降噪：requests/urllib3 的每个连接都打 INFO 太吵
_NOISY = {
    "urllib3": logging.WARNING,
    "requests": logging.WARNING,
    "apscheduler": logging.WARNING,
    "httpx": logging.WARNING,
}


def setup_logging(level: str | None = None) -> None:
    """初始化根 logger。幂等，重复调用无副作用。"""
    global _configured
    if _configured:
        return
    resolved = (level or os.environ.get("LIM_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, resolved, logging.INFO))
    for name, lv in _NOISY.items():
        logging.getLogger(name).setLevel(lv)
    _configured = True
