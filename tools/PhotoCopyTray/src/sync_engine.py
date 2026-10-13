"""增量复制引擎：对齐旧版 A2B + LimAnalysis 注塑/外观目标路径。"""

from __future__ import annotations

import hashlib
import fnmatch
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import logger as log
from config import AppConfig

SnapshotFn = Callable[["SyncSnapshot"], None]


@dataclass
class SyncSnapshot:
    status: str = "正常待机"  # 正常待机 / 同步中 / 已暂停 / 异常
    mode_label: str = ""
    identity: str = ""
    source: str = ""
    target: str = ""
    watch_date: str = ""
    last_sync: str = "-"
    current_file: str = "-"
    ok_count: int = 0
    fail_count: int = 0
    total_runs: int = 0
    message: str = ""


@dataclass
class SyncEngine:
    cfg: AppConfig
    on_snapshot: SnapshotFn | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _wake: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: threading.Thread | None = None
    _paused: bool = False
    _manual: bool = False
    _snap: SyncSnapshot = field(default_factory=SyncSnapshot)
    _env_logged: bool = False

    def start(self) -> None:
        self._paused = bool(self.cfg.paused)
        self._publish()
        self._thread = threading.Thread(target=self._loop, name="SyncEngine", daemon=True)
        self._thread.start()
        log.info(f"监控已启动（{self.cfg.mode_label()} {self.cfg.identity_label()}）")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8)

    def update_config(self, cfg: AppConfig) -> None:
        with self._lock:
            self.cfg = cfg
            self._paused = bool(cfg.paused)
        self._publish(message="配置已更新")
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            self.cfg.paused = paused
        log.info("监控已暂停" if paused else "监控已恢复")
        self._publish()
        self._wake.set()

    def request_manual(self) -> None:
        with self._lock:
            self._manual = True
        log.info("收到手动同步请求")
        self._wake.set()

    def snapshot(self) -> SyncSnapshot:
        with self._lock:
            return SyncSnapshot(**self._snap.__dict__)

    def _loop(self) -> None:
        while not self._stop.is_set():
            cfg = self._cfg()
            manual = False
            paused = False
            with self._lock:
                manual = self._manual
                self._manual = False
                paused = self._paused
            if paused and not manual:
                self._publish(status="已暂停")
            else:
                try:
                    self._execute(cfg, manual=manual)
                except Exception as exc:  # noqa: BLE001
                    log.error(f"同步周期异常: {exc}")
                    self._publish(status="异常", message=str(exc)[:200])
            wait = max(1, int(cfg.poll_seconds))
            self._wake.wait(timeout=wait)
            self._wake.clear()

    def _cfg(self) -> AppConfig:
        with self._lock:
            return self.cfg

    def _execute(self, cfg: AppConfig, *, manual: bool) -> None:
        err = cfg.validate()
        if err:
            self._publish(status="异常", message=err)
            if manual:
                log.warn(err)
            return

        source = Path(cfg.source_dir)
        target = cfg.effective_target()
        date_key, date_label = self._today_keys(cfg.mode)
        self._publish(
            status="同步中",
            source=str(source),
            target=str(target),
            watch_date=date_label,
            current_file="-",
            message="",
        )
        if not self._env_logged:
            self._env_logged = True
            log.info(
                "运行环境: 模式="
                f"{cfg.mode_label()}; 标识={cfg.identity_label()}; "
                f"源={source}; 目标={target}; 网络={self._is_network(target)}"
            )

        if not source.is_dir():
            msg = f"源目录不存在: {source}"
            if manual:
                log.warn(msg)
            self._publish(status="正常待机", message=msg if manual else "")
            return

        if not self._ensure_dir(target):
            msg = f"目标路径不可用，请检查网络连接: {target}"
            log.error(msg)
            self._publish(status="异常", message=msg)
            return

        # 源侧优先找当天目录；没有则同步源根下文件（静默等待）
        src_day = self._find_source_day_dir(source, cfg.mode, date_key, date_label)
        if src_day is None:
            if manual:
                log.info("手动同步结束：当天目录不存在，保持静默等待")
            self._bump_run(ok=True)
            self._publish(status="正常待机", last_sync=_now(), message="当天目录不存在")
            return

        dst_day = target / date_label
        if not self._ensure_dir(dst_day):
            self._publish(status="异常", message=f"无法创建目标日期目录: {dst_day}")
            return

        files = self._list_files(src_day, cfg)
        ok = 0
        fail = 0
        for src_file in files:
            if self._stop.is_set():
                break
            rel = src_file.relative_to(src_day)
            dst_file = dst_day / rel
            self._publish(current_file=str(rel).replace("\\", "/"))
            if not self._file_ready(src_file, cfg.file_settle_seconds):
                log.sync(f"文件仍在写入，等待下轮: {rel}")
                continue
            if self._same_file(src_file, dst_file, cfg.compare_mode):
                continue
            if self._copy_with_retry(src_file, dst_file, cfg):
                ok += 1
                log.sync(f"已同步: {rel}")
            else:
                fail += 1

        self._bump_run(ok=(fail == 0), ok_delta=ok, fail_delta=fail)
        log.sync(f"本轮同步完成 成功={ok} 失败={fail} 扫描={len(files)}")
        self._publish(
            status="正常待机" if fail == 0 else "异常",
            last_sync=_now(),
            current_file="-",
            message=f"成功 {ok} / 失败 {fail}",
        )
        log.cleanup(cfg.log_keep_days)

    def _today_keys(self, mode: str) -> tuple[str, str]:
        now = datetime.now()
        ymd = now.strftime("%Y%m%d")
        if (mode or "").lower() == "appearance":
            return ymd, now.strftime("%Y.%m.%d")
        return ymd, ymd

    def _find_source_day_dir(
        self, source: Path, mode: str, ymd: str, dotted: str
    ) -> Path | None:
        candidates = [ymd, dotted, ymd[:4] + "-" + ymd[4:6] + "-" + ymd[6:]]
        # 源本身就是当天目录
        if source.name in candidates and source.is_dir():
            return source
        for name in candidates:
            path = source / name
            if path.is_dir():
                return path
        return None

    def _list_files(self, root: Path, cfg: AppConfig) -> list[Path]:
        exclude_dirs = {d.replace("\\", "/").strip("/").lower() for d in cfg.exclude_dirs}
        out: list[Path] = []
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    rel = path.relative_to(root).as_posix()
                except ValueError:
                    continue
                parts = rel.split("/")
                if any(part.lower() in exclude_dirs for part in parts[:-1]):
                    continue
                if any(self._match(rel, pat) or self._match(path.name, pat) for pat in cfg.exclude_globs):
                    continue
                out.append(path)
        except OSError as exc:
            log.warn(f"枚举当天目录失败: {exc}")
        return out

    def _match(self, text: str, pattern: str) -> bool:
        return fnmatch.fnmatch(text.lower(), pattern.lower())

    def _file_ready(self, path: Path, settle: float) -> bool:
        try:
            size1 = path.stat().st_size
            mtime1 = path.stat().st_mtime
        except OSError:
            return False
        if settle <= 0:
            return True
        time.sleep(min(settle, 1.0))
        try:
            st = path.stat()
            return st.st_size == size1 and st.st_mtime == mtime1
        except OSError:
            return False

    def _same_file(self, src: Path, dst: Path, mode: str) -> bool:
        if not dst.is_file():
            return False
        try:
            ss, ds = src.stat(), dst.stat()
        except OSError:
            return False
        if ss.st_size != ds.st_size:
            return False
        if mode == "md5":
            return self._md5(src) == self._md5(dst)
        # 修改时间允许 2 秒误差（网络盘）
        return abs(ss.st_mtime - ds.st_mtime) < 2.0

    def _md5(self, path: Path) -> str:
        h = hashlib.md5()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _copy_with_retry(self, src: Path, dst: Path, cfg: AppConfig) -> bool:
        last_err = ""
        for attempt in range(1, max(1, cfg.retry_count) + 1):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                self._copy_throttled(src, dst, cfg.speed_limit_kbps)
                try:
                    shutil.copystat(src, dst, follow_symlinks=True)
                except OSError:
                    pass
                return True
            except PermissionError as exc:
                last_err = f"访问被拒绝: {exc}"
            except OSError as exc:
                last_err = f"IO错误: {exc}"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
            log.warn(f"同步重试 {attempt}/{cfg.retry_count}: {last_err}")
            time.sleep(cfg.retry_interval)
        log.error(f"复制失败: {src.name} | {last_err}")
        return False

    def _copy_throttled(self, src: Path, dst: Path, limit_kbps: int) -> None:
        tmp = dst.with_suffix(dst.suffix + ".pctmp")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        chunk = 256 * 1024
        limit = max(0, int(limit_kbps)) * 1024
        with src.open("rb") as rf, tmp.open("wb") as wf:
            while True:
                data = rf.read(chunk)
                if not data:
                    break
                wf.write(data)
                if limit > 0:
                    time.sleep(len(data) / limit)
        tmp.replace(dst)

    def _ensure_dir(self, path: Path) -> bool:
        for attempt in range(1, 4):
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path.is_dir()
            except PermissionError:
                log.warn(f"创建目录权限被拒绝 (尝试 {attempt}/3): {path}")
            except OSError as exc:
                log.warn(f"创建目录IO错误 (尝试 {attempt}/3): {path} | {exc}")
            time.sleep(1.0)
        if self._is_network(path):
            return self._ps_mkdir(path)
        return False

    def _ps_mkdir(self, path: Path) -> bool:
        import subprocess

        quoted = str(path).replace("'", "''")
        cmd = (
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"New-Item -ItemType Directory -Path '{quoted}' -Force | Out-Null",
        )
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and path.is_dir():
                log.info(f"PowerShell 兜底创建目录成功: {path}")
                return True
            log.warn(f"PowerShell 兜底创建目录失败: {path}")
        except Exception as exc:  # noqa: BLE001
            log.warn(f"调用 PowerShell 创建目录异常: {exc}")
        return False

    def _is_network(self, path: Path) -> bool:
        text = str(path)
        return text.startswith("\\\\") or text.startswith("//")

    def _bump_run(self, *, ok: bool, ok_delta: int = 0, fail_delta: int = 0) -> None:
        with self._lock:
            self._snap.total_runs += 1
            self._snap.ok_count += ok_delta
            self._snap.fail_count += fail_delta
            if not ok and fail_delta == 0:
                self._snap.fail_count += 1

    def _publish(self, **kwargs) -> None:
        with self._lock:
            cfg = self.cfg
            self._snap.mode_label = cfg.mode_label()
            self._snap.identity = cfg.identity_label()
            self._snap.source = str(cfg.source_dir)
            self._snap.target = str(cfg.effective_target())
            if self._paused and "status" not in kwargs:
                self._snap.status = "已暂停"
            for key, value in kwargs.items():
                setattr(self._snap, key, value)
            snap = SyncSnapshot(**self._snap.__dict__)
        if self.on_snapshot:
            try:
                self.on_snapshot(snap)
            except Exception:  # noqa: BLE001
                pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
