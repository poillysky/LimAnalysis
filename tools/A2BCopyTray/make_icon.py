# -*- coding: utf-8 -*-
"""
生成 A2BCopyTray 的 app.ico（多尺寸）。

设计：圆角方砖（蓝色渐变）+ 两张交叠的白色圆角卡片 —— 通用「复制」语义，
几何形在 16px 上仍能分辨，不用文字/细节笔画（那些在 16px 会糊成一团）。

用法：
    python make_icon.py                # 写入 ../app.ico 并输出预览图
    python make_icon.py --top 58,150,240 --bottom 17,94,178

改配色 / 改形状后重跑即可，无需手工拼 ico。
"""

from __future__ import annotations

import argparse
import io
import os
import struct
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow：pip install pillow")

S = 1024                    # 主图边长（超采样，最后统一 LANCZOS 缩小）
TILE_RADIUS = 224           # 方砖圆角
SHEET = 474                 # 卡片边长
OFFSET = 182                # 后卡片相对前卡片的偏移（右上）
SHEET_RADIUS = 72
BACK_ALPHA = 170            # 后卡片半透明，与前卡片拉开层次

# 输出尺寸：覆盖 Explorer / 任务栏 / 托盘 / 高 DPI 的各种取值
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

HERE = os.path.dirname(os.path.abspath(__file__))


def _gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """竖向线性渐变（先做 1px 宽的柱子再横向拉伸，避免逐像素循环）。"""
    col = Image.new("RGB", (1, size))
    px = col.load()
    for y in range(size):
        t = y / (size - 1) if size > 1 else 0.0
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return col.resize((size, size), Image.NEAREST)


def render_master(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    # 1) 渐变底
    grad = _gradient(S, top, bottom)

    # 2) 圆角方砖：用 L 蒙版把渐变裁成圆角
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=TILE_RADIUS, fill=255)
    tile.paste(grad, (0, 0), mask)

    # 3) 两张卡片。前卡片在左下、后卡片在右上，两者按 o 对角偏移，
    #    并让整体包围盒在方砖内严格居中。
    a = (S - OFFSET - SHEET) // 2          # 前卡片 x
    b = (S + OFFSET - SHEET) // 2          # 前卡片 y
    front = [a, b, a + SHEET, b + SHEET]
    back = [a + OFFSET, b - OFFSET, a + OFFSET + SHEET, b - OFFSET + SHEET]

    sheets = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(sheets)
    d.rounded_rectangle(back, radius=SHEET_RADIUS, fill=(255, 255, 255, BACK_ALPHA))
    d.rounded_rectangle(front, radius=SHEET_RADIUS, fill=(255, 255, 255, 255))

    return Image.alpha_composite(tile, sheets)


def build_ico(master: Image.Image, sizes=SIZES) -> bytes:
    """手写 ICO：每条目录项都是 PNG 负载（Vista+ 支持，与旧图标格式一致）。"""
    blobs: list[tuple[int, bytes]] = []
    for s in sizes:
        frame = master if master.width == s else master.resize((s, s), Image.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="PNG", optimize=True)
        blobs.append((s, buf.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(blobs))
    directory = b""
    offset = 6 + 16 * len(blobs)
    payload = b""
    for s, blob in blobs:
        w = 0 if s >= 256 else s          # 256 在目录里写 0
        h = 0 if s >= 256 else s
        directory += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        payload += blob
    return header + directory + payload


def save_preview(master: Image.Image, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    master.resize((512, 512), Image.LANCZOS).save(os.path.join(out_dir, "app-icon.png"))

    # 尺寸预览条：贴到浅灰底上，模拟真实桌面里的观感
    pad, bg = 16, (243, 245, 248, 255)
    strip_w = pad + sum(s + pad for s in SIZES)
    strip_h = max(SIZES) + pad * 2
    strip = Image.new("RGBA", (strip_w, strip_h), bg)
    x = pad
    for s in SIZES:
        frame = master.resize((s, s), Image.LANCZOS)
        strip.alpha_composite(frame, (x, pad + (max(SIZES) - s) // 2))
        x += s + pad
    strip.save(os.path.join(out_dir, "app-icon-sizes.png"))


def _rgb(text: str) -> tuple[int, int, int]:
    parts = [int(v) for v in text.split(",")]
    if len(parts) != 3 or any(not 0 <= v <= 255 for v in parts):
        raise argparse.ArgumentTypeError("需要 R,G,B 三个 0~255 的数")
    return parts[0], parts[1], parts[2]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 A2BCopyTray 应用图标")
    ap.add_argument("--top", type=_rgb, default=(58, 150, 240), help="渐变起始色 R,G,B")
    ap.add_argument("--bottom", type=_rgb, default=(17, 94, 178), help="渐变结束色 R,G,B")
    ap.add_argument("--out", default=os.path.join(HERE, "app.ico"), help="输出 ico 路径")
    ap.add_argument("--preview-dir", default=os.path.join(HERE, "shots"), help="预览图目录")
    args = ap.parse_args()

    master = render_master(args.top, args.bottom)
    data = build_ico(master)
    with open(args.out, "wb") as f:
        f.write(data)

    save_preview(master, args.preview_dir)
    print(f"wrote {args.out}  {len(data)} bytes  sizes={list(SIZES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
