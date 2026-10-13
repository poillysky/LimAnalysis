"""主界面：状态面板。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from logger import today_log_path
from sync_engine import SyncSnapshot


class MainWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_sync: Callable[[], None],
        on_settings: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_hide: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title("PhotoCopyTray 增量复制")
        self.geometry("560x360")
        self.minsize(520, 320)
        self._on_sync = on_sync
        self._on_settings = on_settings
        self._on_toggle_pause = on_toggle_pause
        self._on_hide = on_hide
        self._paused = False

        self.vars = {
            "mode": tk.StringVar(value="-"),
            "identity": tk.StringVar(value="-"),
            "status": tk.StringVar(value="-"),
            "date": tk.StringVar(value="-"),
            "source": tk.StringVar(value="-"),
            "target": tk.StringVar(value="-"),
            "last": tk.StringVar(value="-"),
            "stats": tk.StringVar(value="-"),
            "current": tk.StringVar(value="-"),
            "message": tk.StringVar(value=""),
        }
        self.pause_btn_text = tk.StringVar(value="暂停监控")
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._hide)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        rows = [
            ("运行模式", "mode"),
            ("站点标识", "identity"),
            ("运行状态", "status"),
            ("监控日期", "date"),
            ("源目录", "source"),
            ("目标目录", "target"),
            ("最后同步", "last"),
            ("今日统计", "stats"),
            ("当前文件", "current"),
        ]
        for i, (label, key) in enumerate(rows):
            ttk.Label(root, text=label, width=10).grid(row=i, column=0, sticky="nw", pady=3)
            ttk.Label(root, textvariable=self.vars[key], wraplength=400).grid(
                row=i, column=1, sticky="w", pady=3
            )
        ttk.Label(root, textvariable=self.vars["message"], foreground="#a00").grid(
            row=len(rows), column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        btns = ttk.Frame(root)
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", pady=12)
        ttk.Button(btns, text="立即同步", command=self._on_sync).pack(side="left", padx=4)
        ttk.Button(btns, text="系统配置", command=self._on_settings).pack(side="left", padx=4)
        ttk.Button(btns, textvariable=self.pause_btn_text, command=self._on_toggle_pause).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="导出日志", command=self._export_log).pack(side="left", padx=4)
        ttk.Button(btns, text="隐藏到托盘", command=self._hide).pack(side="left", padx=4)

    def apply_snapshot(self, snap: SyncSnapshot) -> None:
        self.vars["mode"].set(snap.mode_label or "-")
        self.vars["identity"].set(snap.identity or "-")
        self.vars["status"].set(snap.status or "-")
        self.vars["date"].set(snap.watch_date or "-")
        self.vars["source"].set(snap.source or "-")
        self.vars["target"].set(snap.target or "-")
        self.vars["last"].set(snap.last_sync or "-")
        self.vars["stats"].set(
            f"成功 {snap.ok_count} / 失败 {snap.fail_count} / 总次数 {snap.total_runs}"
        )
        self.vars["current"].set(snap.current_file or "-")
        self.vars["message"].set(snap.message or "")
        self._paused = snap.status == "已暂停"
        self.pause_btn_text.set("恢复监控" if self._paused else "暂停监控")

    def _hide(self) -> None:
        self.withdraw()
        self._on_hide()

    def _export_log(self) -> None:
        src = today_log_path()
        if not src.is_file():
            messagebox.showinfo("导出日志", "今日尚未生成日志文件。", parent=self)
            return
        dest = filedialog.asksaveasfilename(
            parent=self,
            title="导出日志",
            defaultextension=".log",
            initialfile=f"PhotoCopyTray_{src.stem}.log",
            filetypes=[("Log Files", "*.log"), ("All Files", "*.*")],
        )
        if not dest:
            return
        try:
            dest_path = __import__("pathlib").Path(dest)
            dest_path.write_bytes(src.read_bytes())
            messagebox.showinfo("导出日志", "日志导出完成。", parent=self)
        except OSError as exc:
            messagebox.showerror("导出日志", str(exc), parent=self)

    def show_front(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
