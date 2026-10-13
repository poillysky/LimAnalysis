"""按日滚动日志。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from config import logs_dir


def write(level: str, message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} [{level}] {message}"
    path = logs_dir() / f"{datetime.now():%Y%m%d}.log"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def info(message: str) -> None:
    write("信息", message)


def sync(message: str) -> None:
    write("同步", message)


def warn(message: str) -> None:
    write("警告", message)


def error(message: str) -> None:
    write("错误", message)


def cleanup(keep_days: int) -> None:
    root = logs_dir()
    cutoff = datetime.now() - timedelta(days=max(1, int(keep_days)))
    for path in root.glob("*.log"):
        try:
            stem = path.stem
            if len(stem) == 8 and stem.isdigit():
                day = datetime.strptime(stem, "%Y%m%d")
                if day < cutoff:
                    path.unlink(missing_ok=True)
        except OSError:
            continue


def today_log_path() -> Path:
    return logs_dir() / f"{datetime.now():%Y%m%d}.log"
