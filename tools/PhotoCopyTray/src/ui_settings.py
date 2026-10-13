"""系统配置窗口。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import AppConfig, clone_config, normalize_config


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        cfg: AppConfig,
        on_save: Callable[[AppConfig], None],
    ) -> None:
        super().__init__(master)
        self.title("PhotoCopyTray 系统配置")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._on_save = on_save
        self._cfg = clone_config(cfg)

        self.mode = tk.StringVar(value=self._cfg.mode)
        self.machine = tk.StringVar(value=self._cfg.machine)
        self.project = tk.StringVar(value=self._cfg.project)
        self.source_dir = tk.StringVar(value=self._cfg.source_dir)
        self.target_root = tk.StringVar(value=self._cfg.target_root)
        self.poll_seconds = tk.IntVar(value=self._cfg.poll_seconds)
        self.file_settle = tk.DoubleVar(value=self._cfg.file_settle_seconds)
        self.retry_count = tk.IntVar(value=self._cfg.retry_count)
        self.retry_interval = tk.DoubleVar(value=self._cfg.retry_interval)
        self.speed_limit = tk.IntVar(value=self._cfg.speed_limit_kbps)
        self.log_keep = tk.IntVar(value=self._cfg.log_keep_days)
        self.compare_mode = tk.StringVar(value=self._cfg.compare_mode)
        self.auto_start = tk.BooleanVar(value=self._cfg.auto_start)
        self.exclude_dirs = tk.StringVar(value="\n".join(self._cfg.exclude_dirs))
        self.exclude_globs = tk.StringVar(value="\n".join(self._cfg.exclude_globs))

        self._build()
        self._on_mode_change()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self._center)

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")

        row = 0
        ttk.Label(root, text="运行模式").grid(row=row, column=0, sticky="w", **pad)
        mode_box = ttk.Frame(root)
        mode_box.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        ttk.Radiobutton(
            mode_box,
            text="注塑机",
            value="mold",
            variable=self.mode,
            command=self._on_mode_change,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            mode_box,
            text="外观机",
            value="appearance",
            variable=self.mode,
            command=self._on_mode_change,
        ).pack(side="left")

        row += 1
        self.project_label = ttk.Label(root, text="项目名")
        self.project_label.grid(row=row, column=0, sticky="w", **pad)
        self.project_entry = ttk.Entry(root, textvariable=self.project, width=42)
        self.project_entry.grid(row=row, column=1, columnspan=2, sticky="we", **pad)

        row += 1
        self.machine_label = ttk.Label(root, text="机台号")
        self.machine_label.grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(root, textvariable=self.machine, width=42).grid(
            row=row, column=1, columnspan=2, sticky="we", **pad
        )

        row += 1
        ttk.Label(root, text="本地源目录").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(root, textvariable=self.source_dir, width=42).grid(
            row=row, column=1, sticky="we", **pad
        )
        ttk.Button(root, text="浏览...", command=self._browse_source).grid(
            row=row, column=2, **pad
        )

        row += 1
        ttk.Label(root, text="目标根目录").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(root, textvariable=self.target_root, width=42).grid(
            row=row, column=1, sticky="we", **pad
        )
        ttk.Button(root, text="浏览...", command=self._browse_target).grid(
            row=row, column=2, **pad
        )

        row += 1
        self.target_hint = ttk.Label(root, text="", foreground="#666")
        self.target_hint.grid(row=row, column=1, columnspan=2, sticky="w", **pad)

        row += 1
        ttk.Separator(root).grid(row=row, column=0, columnspan=3, sticky="we", pady=8)

        row += 1
        opts = ttk.Frame(root)
        opts.grid(row=row, column=0, columnspan=3, sticky="we")
        self._num(opts, 0, "监控延迟(秒)", self.poll_seconds)
        self._num(opts, 1, "文件释放等待", self.file_settle)
        self._num(opts, 2, "失败重试次数", self.retry_count)
        self._num(opts, 3, "重试间隔(秒)", self.retry_interval)
        self._num(opts, 4, "限速(KB/s)", self.speed_limit)
        self._num(opts, 5, "日志保留天数", self.log_keep)

        row += 1
        ttk.Label(root, text="文件判断模式").grid(row=row, column=0, sticky="w", **pad)
        ttk.Combobox(
            root,
            textvariable=self.compare_mode,
            values=("fast", "md5"),
            state="readonly",
            width=18,
        ).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(root, text="fast=大小+时间 / md5=校验").grid(
            row=row, column=2, sticky="w", **pad
        )

        row += 1
        ttk.Checkbutton(root, text="开机自启", variable=self.auto_start).grid(
            row=row, column=1, sticky="w", **pad
        )

        row += 1
        ttk.Label(root, text="排除目录").grid(row=row, column=0, sticky="nw", **pad)
        self.dirs_text = tk.Text(root, width=42, height=4)
        self.dirs_text.grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        self.dirs_text.insert("1.0", self.exclude_dirs.get())

        row += 1
        ttk.Label(root, text="排除通配").grid(row=row, column=0, sticky="nw", **pad)
        self.globs_text = tk.Text(root, width=42, height=3)
        self.globs_text.grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        self.globs_text.insert("1.0", self.exclude_globs.get())

        row += 1
        btns = ttk.Frame(root)
        btns.grid(row=row, column=0, columnspan=3, sticky="e", pady=10)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="保存", command=self._save).pack(side="right", padx=4)

        self.mode.trace_add("write", lambda *_: self._on_mode_change())
        self.machine.trace_add("write", lambda *_: self._update_hint())
        self.project.trace_add("write", lambda *_: self._update_hint())
        self.target_root.trace_add("write", lambda *_: self._update_hint())

    def _num(self, parent: ttk.Frame, col: int, label: str, var: tk.Variable) -> None:
        box = ttk.Frame(parent)
        box.grid(row=0, column=col, padx=6, pady=2, sticky="w")
        ttk.Label(box, text=label).pack(anchor="w")
        ttk.Entry(box, textvariable=var, width=10).pack(anchor="w")

    def _on_mode_change(self) -> None:
        appearance = self.mode.get() == "appearance"
        state = "normal" if appearance else "disabled"
        self.project_entry.configure(state=state)
        self.machine_label.configure(text="外观机号" if appearance else "机台号")
        self.project_label.configure(
            text="项目名（NAS 文件夹）" if appearance else "项目名"
        )
        self._update_hint()

    def _update_hint(self) -> None:
        cfg = self._draft()
        self.target_hint.configure(text=f"实际写入: {cfg.effective_target()}")

    def _draft(self) -> AppConfig:
        return normalize_config(
            {
                "mode": self.mode.get(),
                "machine": self.machine.get(),
                "project": self.project.get(),
                "source_dir": self.source_dir.get(),
                "target_root": self.target_root.get(),
                "poll_seconds": self.poll_seconds.get(),
                "file_settle_seconds": self.file_settle.get(),
                "retry_count": self.retry_count.get(),
                "retry_interval": self.retry_interval.get(),
                "speed_limit_kbps": self.speed_limit.get(),
                "log_keep_days": self.log_keep.get(),
                "compare_mode": self.compare_mode.get(),
                "auto_start": self.auto_start.get(),
                "exclude_dirs": self.dirs_text.get("1.0", "end"),
                "exclude_globs": self.globs_text.get("1.0", "end"),
                "paused": self._cfg.paused,
            }
        )

    def _browse_source(self) -> None:
        path = filedialog.askdirectory(title="选择本地源目录")
        if path:
            self.source_dir.set(path)

    def _browse_target(self) -> None:
        path = filedialog.askdirectory(title="选择目标根目录（可为已映射的网络盘）")
        if path:
            self.target_root.set(path)

    def _save(self) -> None:
        cfg = self._draft()
        err = cfg.validate()
        if err:
            messagebox.showwarning("配置校验", err, parent=self)
            return
        self._on_save(cfg)
        self.destroy()
