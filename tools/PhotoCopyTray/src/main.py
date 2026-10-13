"""PhotoCopyTray 入口：托盘 + 注塑/外观增量复制。"""

from __future__ import annotations

import atexit
import sys
import threading
import traceback
from pathlib import Path

# 保证从任意工作目录启动都能 import 同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk
from tkinter import messagebox

import autostart
import logger as log
from config import (
    APP_NAME,
    SINGLE_INSTANCE_MUTEX,
    load_config,
    save_config,
)
from sync_engine import SyncEngine, SyncSnapshot
from ui_main import MainWindow
from ui_settings import SettingsDialog


class SingleInstance:
    def __init__(self, name: str) -> None:
        self._handle = None
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            self._handle = kernel32.CreateMutexW(None, False, name)
            self.owned = kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        except Exception:  # noqa: BLE001
            self.owned = True

    def release(self) -> None:
        if not self._handle:
            return
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
        except Exception:  # noqa: BLE001
            pass
        self._handle = None


class App:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.engine = SyncEngine(self.cfg, on_snapshot=self._on_snapshot)
        self.main: MainWindow | None = None
        self._tray = None
        self._tray_thread: threading.Thread | None = None
        self._icon_images = None

    def run(self) -> None:
        log.info(f"{APP_NAME} 客户端启动")
        autostart.apply(self.cfg.auto_start)
        self.engine.start()
        self._open_main(show=False)
        self._start_tray()
        self.root.mainloop()

    def shutdown(self) -> None:
        try:
            self.engine.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._tray:
                self._tray.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass
        log.info(f"{APP_NAME} 客户端正常退出")

    def _open_main(self, show: bool = True) -> None:
        if self.main is None or not self.main.winfo_exists():
            self.main = MainWindow(
                self.root,
                on_sync=self._manual_sync,
                on_settings=self._open_settings,
                on_toggle_pause=self._toggle_pause,
                on_hide=lambda: None,
            )
            self.main.apply_snapshot(self.engine.snapshot())
        if show:
            self.main.show_front()
        else:
            self.main.withdraw()

    def _open_settings(self) -> None:
        def save(cfg) -> None:
            self.cfg = cfg
            save_config(cfg)
            autostart.apply(cfg.auto_start)
            self.engine.update_config(cfg)
            log.info("配置已保存")
            if self.main and self.main.winfo_exists():
                self.main.apply_snapshot(self.engine.snapshot())

        SettingsDialog(self.root, self.cfg, on_save=save)

    def _manual_sync(self) -> None:
        self.engine.request_manual()

    def _toggle_pause(self) -> None:
        snap = self.engine.snapshot()
        paused = snap.status != "已暂停"
        self.engine.set_paused(paused)
        self.cfg.paused = paused
        save_config(self.cfg)

    def _on_snapshot(self, snap: SyncSnapshot) -> None:
        def apply() -> None:
            if self.main and self.main.winfo_exists():
                self.main.apply_snapshot(snap)
            self._update_tray_title(snap)

        try:
            self.root.after(0, apply)
        except Exception:  # noqa: BLE001
            pass

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            log.warn("未安装 pystray/Pillow，托盘不可用；将显示主界面。pip install pystray Pillow")
            self._open_main(show=True)
            return

        image = self._make_icon(Image, ImageDraw)
        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", lambda: self.root.after(0, lambda: self._open_main(True))),
            pystray.MenuItem("系统配置", lambda: self.root.after(0, self._open_settings)),
            pystray.MenuItem("立即手动同步", lambda: self.root.after(0, self._manual_sync)),
            pystray.MenuItem(
                "暂停/恢复监控", lambda: self.root.after(0, self._toggle_pause)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", lambda: self.root.after(0, self.shutdown)),
        )
        self._tray = pystray.Icon(APP_NAME, image, APP_NAME, menu)

        def run_icon() -> None:
            assert self._tray is not None
            self._tray.run()

        self._tray_thread = threading.Thread(target=run_icon, name="Tray", daemon=True)
        self._tray_thread.start()

    def _update_tray_title(self, snap: SyncSnapshot) -> None:
        if not self._tray:
            return
        self._tray.title = f"{APP_NAME} - {snap.mode_label} {snap.identity} - {snap.status}"

    def _make_icon(self, Image, ImageDraw):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, 60, 60), fill=(30, 78, 121, 255))
        draw.rectangle((20, 28, 44, 48), fill=(255, 255, 255, 255))
        draw.polygon([(32, 14), (46, 30), (18, 30)], fill=(255, 255, 255, 255))
        return img


def main() -> int:
    locker = SingleInstance(SINGLE_INSTANCE_MUTEX)
    if not locker.owned:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo(APP_NAME, "PhotoCopyTray 托盘程序已在运行。")
            root.destroy()
        except Exception:  # noqa: BLE001
            print("PhotoCopyTray 托盘程序已在运行。")
        return 1
    atexit.register(locker.release)

    try:
        App().run()
        return 0
    except Exception as exc:  # noqa: BLE001
        log.error(f"程序启动失败: {exc}")
        try:
            (Path(__file__).resolve().parent.parent / "startup_error.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        except OSError:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(f"{APP_NAME} 错误", f"程序启动失败: {exc}")
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
