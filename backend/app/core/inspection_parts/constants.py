"""inspection 共享常量。

放在子包里，供 dates / filenames 等拆出的模块复用，避免循环导入。
app/core/inspection.py 仍从 app.core 顶层暴露这些名字（re-export）。
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

CAVITY_LETTERS = frozenset("ABCDEFGHJKLMNPQR")
CAVITY_ORDER = list("ABCDEFGHJKLMNPQR")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
TZ = ZoneInfo("Asia/Shanghai")
VIEWER_STATUSES = ["OK", "定位NG", "底涂不良", "无料NG", "扫码不良", "相机掉线"]
PHOTO_SOURCES = ("mold", "appearance")
APPEARANCE_DIMS = ("tester", "mold")
SOURCE_ROOT_KEYS = {
    "mold": "mold_root_path",
    "appearance": "appearance_root_path",
}
SOURCE_LABELS = {
    "mold": "注塑机",
    "appearance": "自动外观",
}
APPEARANCE_FIXED_SEGMENTS = ("GVIMAGES", "LIM外观检测")
APPEARANCE_SHOT_DIR = "截图"
