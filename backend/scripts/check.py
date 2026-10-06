"""后端统一检查入口：把 lint 与测试串成一条命令。

## 为什么要这个文件

这个仓库已经有两道「机器守卫」——`tests/test_arch_guard.py`（禁止 app.core 反向
依赖上层）和 pyproject.toml 里的 ruff 规则。但守卫只有在**被跑**的时候才有效。
没有统一入口时，实际发生的是一串「记得也要跑那个」的口头约定，最后就是一个都不跑。

本机没有 `make`，所以用零依赖的 Python 脚本（不引入 typer/click，避免为一条
check 命令多装一个包）。跨平台，Windows/Linux/macOS 都能直接跑。

用法：
    python scripts/check.py            # 全部（lint + 测试）
    python scripts/check.py lint       # 只 lint
    python scripts/check.py test       # 只测试
    python scripts/check.py lint --fix # lint 并自动修复可修项

退出码：全通过 0，任一失败 1（可直接用于 CI）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# 用 venv 里的解释器/工具，避免误用系统级 python
VENV_BIN = BACKEND / ".venv" / "Scripts" if sys.platform == "win32" else BACKEND / ".venv" / "bin"
PYTHON = VENV_BIN / ("python.exe" if sys.platform == "win32" else "python")
RUFF = VENV_BIN / ("ruff.exe" if sys.platform == "win32" else "ruff")


def run(name: str, cmd: list[str]) -> bool:
    print(f"\n{'─' * 64}\n{name}\n{'─' * 64}")
    print(f"$ {' '.join(str(c) for c in cmd)}\n")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(BACKEND))
    ok = proc.returncode == 0
    print(f"\n{'✓' if ok else '✗'} {name}  ({time.time() - t0:.1f}s)")
    return ok


def ruff_cmd(fix: bool) -> list[str] | None:
    """返回 ruff 命令；ruff 不存在时给出手动获取指引并返回 None。

    ruff 不在 PyPI 常规安装路径上能装到（本机 pip 走不通代理），
    所以单独提供 scripts/_fetch_ruff.py 拉独立二进制。
    """
    if not RUFF.exists():
        print(f"✗ 找不到 {RUFF}\n")
        print("  本机 pip 走不通代理，请用脚本获取 ruff 二进制：")
        print(f"    {PYTHON} scripts/_fetch_ruff.py\n")
        return None
    cmd = [str(RUFF), "check", ".", "--output-format", "concise"]
    if fix:
        cmd.append("--fix")
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(description="后端统一检查")
    ap.add_argument("target", nargs="?", default="all", choices=["all", "lint", "test"])
    ap.add_argument("--fix", action="store_true", help="lint 时自动修复可修项")
    args = ap.parse_args()

    if not PYTHON.exists():
        print(f"✗ 找不到解释器 {PYTHON}，请先创建 .venv")
        return 1

    results: list[tuple[str, bool]] = []

    if args.target in ("all", "lint"):
        cmd = ruff_cmd(args.fix)
        if cmd is None:
            results.append(("lint", False))
        else:
            results.append(("lint", run("ruff check", cmd)))

    if args.target in ("all", "test"):
        # 用 unittest 而非 pytest：本机 pip 装不上 pytest，而 unittest 零依赖。
        # 现有用例全部是 unittest 风格，将来换成 pytest 也能直接跑。
        # 保持与手工验证时一致的调用形式（-s tests，在 backend/ 下执行）。
        results.append((
            "test",
            run("unittest", [str(PYTHON), "-m", "unittest", "discover", "-s", "tests"]),
        ))

    print(f"\n{'=' * 64}")
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    failed = [n for n, ok in results if not ok]
    print("=" * 64)

    if failed:
        print(f"\n失败：{', '.join(failed)}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
