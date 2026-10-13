"""配置读写：注塑机 / 外观机两种模式，规则各用各的字段。"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "PhotoCopyTray"
SINGLE_INSTANCE_MUTEX = "Global\\PhotoCopyTray.SingleInstance"

# 与 LimAnalysis inspection 识别规则对齐
APPEARANCE_FIXED_SEGMENTS = ("GVIMAGES", "LIM外观检测")


@dataclass
class AppConfig:
    """站点复制配置。

    mode=mold（注塑机）：需要 machine；目标 = target_root/machine/
    mode=appearance（外观机）：需要 project + machine(外观机号)；
      目标 = target_root/project/machine/GVIMAGES/LIM外观检测/
    """

    mode: str = "mold"  # mold | appearance
    machine: str = ""
    project: str = ""
    source_dir: str = r"C:\PhotoSource"
    target_root: str = r"\\SERVER\Share\Photos"
    exclude_dirs: list[str] = field(default_factory=lambda: ["temp", "cache", "Thumbs"])
    exclude_globs: list[str] = field(
        default_factory=lambda: ["*.tmp", "*.temp", "*.part", "*.a2btmp"]
    )
    poll_seconds: int = 5
    file_settle_seconds: float = 2.0
    retry_count: int = 3
    retry_interval: float = 2.0
    speed_limit_kbps: int = 0  # 0 = 不限速
    log_keep_days: int = 14
    auto_start: bool = False
    compare_mode: str = "fast"  # fast | md5
    paused: bool = False

    def validate(self) -> str | None:
        mode = (self.mode or "").strip().lower()
        if mode not in ("mold", "appearance"):
            return "模式必须是注塑机或外观机"
        if not str(self.source_dir or "").strip():
            return "源目录不能为空"
        if not str(self.target_root or "").strip():
            return "目标根目录不能为空"
        if not str(self.machine or "").strip():
            return "机台号不能为空" if mode == "mold" else "外观机号不能为空"
        if mode == "appearance" and not str(self.project or "").strip():
            return "外观机模式需要填写项目名（与 NAS 上项目文件夹一致）"
        return None

    def effective_target(self) -> Path:
        root = Path(str(self.target_root).strip())
        machine = str(self.machine).strip()
        if (self.mode or "").strip().lower() == "appearance":
            project = str(self.project).strip()
            path = root / project / machine
            for seg in APPEARANCE_FIXED_SEGMENTS:
                path = path / seg
            return path
        return root / machine

    def mode_label(self) -> str:
        return "注塑机" if (self.mode or "").lower() == "mold" else "外观机"

    def identity_label(self) -> str:
        if (self.mode or "").lower() == "appearance":
            return f"{self.project}/{self.machine}"
        return str(self.machine or "-")


def app_dir() -> Path:
    """EXE 旁或源码旁：放 config.json / logs。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return app_dir() / "config.json"


def logs_dir() -> Path:
    path = app_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_config() -> AppConfig:
    return AppConfig()


def load_config() -> AppConfig:
    path = config_path()
    if not path.is_file():
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_config()
    return normalize_config(raw)


def save_config(cfg: AppConfig) -> None:
    data = asdict(normalize_config(asdict(cfg)))
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_config(raw: dict | AppConfig | None) -> AppConfig:
    base = default_config()
    if isinstance(raw, AppConfig):
        data = asdict(raw)
    else:
        data = dict(raw or {})
    mode = str(data.get("mode") or base.mode).strip().lower()
    if mode not in ("mold", "appearance"):
        mode = "mold"
    exclude_dirs = _as_str_list(data.get("exclude_dirs"), base.exclude_dirs)
    exclude_globs = _as_str_list(data.get("exclude_globs"), base.exclude_globs)
    compare = str(data.get("compare_mode") or base.compare_mode).strip().lower()
    if compare not in ("fast", "md5"):
        compare = "fast"
    return AppConfig(
        mode=mode,
        machine=str(data.get("machine") or "").strip(),
        project=str(data.get("project") or "").strip(),
        source_dir=str(data.get("source_dir") or base.source_dir).strip(),
        target_root=str(data.get("target_root") or base.target_root).strip(),
        exclude_dirs=exclude_dirs,
        exclude_globs=exclude_globs,
        poll_seconds=max(1, int(data.get("poll_seconds") or base.poll_seconds)),
        file_settle_seconds=max(
            0.0, float(data.get("file_settle_seconds") or base.file_settle_seconds)
        ),
        retry_count=max(1, int(data.get("retry_count") or base.retry_count)),
        retry_interval=max(0.5, float(data.get("retry_interval") or base.retry_interval)),
        speed_limit_kbps=max(0, int(data.get("speed_limit_kbps") or 0)),
        log_keep_days=max(1, int(data.get("log_keep_days") or base.log_keep_days)),
        auto_start=bool(data.get("auto_start", base.auto_start)),
        compare_mode=compare,
        paused=bool(data.get("paused", False)),
    )


def _as_str_list(value, fallback: list[str]) -> list[str]:
    if value is None:
        return list(fallback)
    if isinstance(value, str):
        lines = [line.strip() for line in value.replace(",", "\n").splitlines()]
        return [line for line in lines if line]
    if isinstance(value, (list, tuple)):
        out = [str(item).strip() for item in value if str(item).strip()]
        return out or list(fallback)
    return list(fallback)


def clone_config(cfg: AppConfig) -> AppConfig:
    return normalize_config(deepcopy(asdict(cfg)))
