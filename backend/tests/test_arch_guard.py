"""架构守卫：禁止 app.core 反向依赖 collector / processor。

## 为什么需要这个文件

重构前``app/core/ads_query.py`` 与 ``app/core/defect_store.py`` 在**模块顶层**
``from collector.raw_loader import ident, q`` —— 最底层依赖最上层。
当时没炸纯粹因为 ``collector/__init__.py`` 是空的、``raw_loader`` 的模块级代码
恰好不 import app.core。**靠巧合活着。** 任何人往 raw_loader 顶部加一行
``from app.core import db``，``import app.core.ads_query`` 就ImportError。

2026-10-06 已把这批工具函数下沉到 ``app.core.sql_ident``，倒挂解除。
本守卫的作用是让「解除了」这件事变成**可执行的断言**，而不是靠人记。

## 规则

app.core 是最底层，**不允许** import 上层的 collector / processor。
需要在 app.core 里用上层的东西，说明那个东西放错了位置 —— 下沉它，
而不是在这里加豁免。

跑法：cd backend && .venv/Scripts/python.exe -m unittest tests.test_arch_guard
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP_CORE = BACKEND / "app" / "core"

# app.core 唯一允许的上层依赖目标：都是「延迟导入」豁免，
# 因为它们在函数体内部而非模块顶层，不构成加载期倒挂。
ALLOWED_DEFERRED = {
    # 目前为空 —— 保留这层是为了将来真有正当理由时能有意识地登记，
    # 而不是直接删守卫。登记时必须写清为什么不能下沉。
}


def _iter_imports(path: Path):
    """产出 (module, lineno, is_deferred)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    func_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                func_lines.add(ln)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno, node.lineno in func_lines
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno, node.lineno in func_lines


class ArchGuardTest(unittest.TestCase):
    def test_app_core_does_not_import_upper_layers(self) -> None:
        """app/core 下任何文件都不得 import collector / processor。"""
        violations: list[str] = []
        for py in sorted(APP_CORE.rglob("*.py")):
            rel = py.relative_to(BACKEND).as_posix()
            for module, lineno, deferred in _iter_imports(py):
                root = module.split(".")[0]
                if root not in {"collector", "processor"}:
                    continue
                if deferred and f"{rel}:{module}" in ALLOWED_DEFERRED:
                    continue
                kind = "函数内延迟导入" if deferred else "模块顶层导入"
                violations.append(f"{rel}:{lineno} {kind} {module}")
        self.assertEqual(
            violations,
            [],
            "app/core 反向依赖了上层包。\n"
            "app.core 是最底层，要用上层的东西请把它下沉到 app/core/ 下"
            "（参考 app/core/sql_ident.py 的做法），而不是在这里 import。\n"
            + "\n".join(f"  - {v}" for v in violations),
        )

    def test_sql_ident_has_no_heavy_deps(self) -> None:
        """sql_ident.py 必须零依赖（只准 import re / __future__）。

        它存在的全部意义就是当最底层的公共工具。哪天它开始import sqlalchemy
        或 app.core 的别的东西，说明它被塞进了不属于它的职责。
        """
        target = APP_CORE / "sql_ident.py"
        self.assertTrue(target.exists(), "app/core/sql_ident.py 不见了")
        bad: list[str] = []
        for module, lineno, _d in _iter_imports(target):
            if module in {"re", "__future__"}:
                continue
            bad.append(f"sql_ident.py:{lineno} import {module}")
        self.assertEqual(bad, [], f"sql_ident.py 只能 import re：\n{bad}")

    def test_app_core_imports_do_not_drag_in_collector(self) -> None:
        """运行时验证：import app.core.ads_query 不该把 collector 拉进 sys.modules。

        这是静态检查的真实兜底 —— 哪怕有人用 importlib 动态导入绕过 AST 检查，
        这一条也会挂。
        """
        import subprocess
        import sys

        code = (
            "import sys; import app.core.ads_query, app.core.defect_store;"
            "print('LEAK' if 'collector' in sys.modules else 'CLEAN')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"导入失败：\n{proc.stderr}")
        self.assertIn(
            "CLEAN",
            proc.stdout,
            "import app.core.* 把 collector 拉进来了 —— 下层依赖上层又回来了。",
        )


if __name__ == "__main__":
    unittest.main()
