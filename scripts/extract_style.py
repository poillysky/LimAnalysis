#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 .vue 里的大块内联 <style scoped> 机械外移为同目录 styles/scoped.scss。

只做位置搬移，不改任何选择器/声明 —— CSS 等价性由「改前/改后构建产物逐条比对」
验证（scoped hash 除外，它由文件内容算出，本就会变）。

用法：python extract_style.py <file.vue> [...]
"""
import io
import os
import sys


def split_style(lines):
    """定位文件里所有 <style ...> ... </style> 块的 (start, end) 行下标（0 基，闭区间）。"""
    blocks = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("<style"):
            j = i + 1
            while j < len(lines) and lines[j].strip() != "</style>":
                j += 1
            if j >= len(lines):
                raise SystemExit(f"第 {i+1} 行的 <style> 没有闭合")
            blocks.append((i, j, s))
            i = j + 1
        else:
            i += 1
    return blocks


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        lines = io.open(path, encoding="utf-8").read().split("\n")
        blocks = split_style(lines)
        if not blocks:
            print(f"skip {path}: 没有 <style> 块")
            continue

        d = os.path.dirname(path) or "."
        # 目录名按 .vue 文件名取，避免同级的 etl.vue / sfc.vue / agg.vue 共用一个
        # styles/ 时互相覆盖（这三个页面都在 views/feature/ 下）。
        base = os.path.splitext(os.path.basename(path))[0]
        styles_dir = os.path.join(d, base + ".styles")
        os.makedirs(styles_dir, exist_ok=True)

        # 从后往前替换，避免行号漂移
        for start, end, tag in reversed(blocks):
            scoped = "scoped" in tag
            body = lines[start + 1 : end]
            name = "scoped.scss" if scoped else "global.scss"
            dst = os.path.join(styles_dir, name)
            if os.path.exists(dst):
                raise SystemExit(f"{dst} 已存在，先删掉再跑（避免覆盖别人的改动）")

            hdr = [
                f"// 由 {os.path.basename(path)} 的内联 <style> 外移（2026-10-06）。",
                "// 样式逐条机械搬移，未做任何视觉改动。",
                "// " + ("仍由 .vue 的 scoped 属性保证隔离。" if scoped else
                         "必须是非 scoped：teleport 到 body 的浮层匹配不到 data-v 属性。"),
                "",
            ]
            io.open(dst, "w", encoding="utf-8", newline="\n").write("\n".join(hdr + body) + "\n")

            new_block = ['<style lang="scss"{}>'.format(" scoped" if scoped else ""),
                         f'@import "./{base}.styles/{name}";',
                         "</style>"]
            lines[start : end + 1] = new_block

        io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
        print(f"ok   {path}: {len(blocks)} 个 style 块已外移 -> {styles_dir}")


if __name__ == "__main__":
    main()
