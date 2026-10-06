"""扫后端包依赖图，找 app ↔ processor / collector 循环依赖的切分层。

用法：在 backend/ 下跑  python scripts/_depgraph.py
输出：包级依赖、跨包边（含「顶层导入 / 函数内延迟导入」标注）。
"""

from __future__ import annotations

import ast
import collections
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".venv", "__pycache__", "node_modules", ".git", "tests"}
LAYERS = ("app", "collector", "processor")


def rel_files() -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            if fn.endswith(".py"):
                p = os.path.join(dirpath, fn)
                out.append(os.path.relpath(p, ROOT).replace("\\", "/"))
    return sorted(out)


def modname(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect() -> list[tuple[str, str, int, bool]]:
    edges: list[tuple[str, str, int, bool]] = []
    for rel in rel_files():
        path = os.path.join(ROOT, rel)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:  # pragma: no cover - 只在源码坏了时触发
            print(f"!! parse fail {rel}: {exc}")
            continue
        me = modname(rel)

        func_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    func_lines.add(ln)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            deferred = getattr(node, "lineno", 0) in func_lines
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append((me, alias.name, node.lineno, deferred))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                edges.append((me, node.module, node.lineno, deferred))
    return edges


def main() -> None:
    edges = collect()

    def layer(mod: str) -> str:
        return mod.split(".")[0] if mod else ""

    print("=== 跨顶层包边（X -> Y）===")
    cross = collections.Counter()
    for src, dst, _ln, _d in edges:
        ls, ld = layer(src), layer(dst)
        if ls in LAYERS and ld in LAYERS and ls != ld:
            cross[(ls, ld)] += 1
    for (ls, ld), n in sorted(cross.items()):
        print(f"  {ls:10s} -> {ld:10s} {n} 条")

    print()
    print("=== processor / collector -> app.* 每一条 ===")
    for src, dst, ln, d in sorted(edges):
        if layer(src) in {"processor", "collector"} and layer(dst) == "app":
            print(f"  {'延迟' if d else '顶层'}  {src}:{ln} -> {dst}")

    print()
    print("=== app.* -> processor / collector 每一条 ===")
    for src, dst, ln, d in sorted(edges):
        if layer(src) == "app" and layer(dst) in {"processor", "collector"}:
            print(f"  {'延迟' if d else '顶层'}  {src}:{ln} -> {dst}")

    print()
    print("=== app.core 内部依赖（判断哪些是纯基础设施）===")
    core: set[str] = set()
    for src, _dst, _ln, _d in edges:
        if src.startswith("app.core."):
            core.add(src)
    for src in sorted(core):
        outs = sorted({
            dst for s, dst, _ln, _d in edges
            if s == src and dst.startswith("app.") and dst != src
        })
        print(f"  {src:32s} -> {', '.join(outs) if outs else '(无)'}")


if __name__ == "__main__":
    main()