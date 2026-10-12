"""原始表 SN / 唯一键列识别。

优先级（配置优先，避免写死项目）：
1. 项目 config.unique_key.column
2. 该项目 ETL 清洗模型的 unique_key（功能管理里可改）
3. 系统默认 unique_key.column
4. 常见别名（F/B/CCoverSN、前盖码、SN…）
5. 任意以 CoverSN 结尾的列（下次 DCoverSN 等无需改代码）
"""

from __future__ import annotations

from app.core.projects import load_system_defaults

# 常见别名；配置名不在此列表也能命中（走第 1～3 步）
_SN_ALIASES = (
    "FCoverSN",
    "BCoverSN",
    "CCoverSN",
    "前盖码",
    "SN",
    "sn",
    "二维码",
    "条码",
    "序列号",
)


def pick_col(columns: list[str], *names: str) -> str | None:
    """按候选名在列清单里找列（大小写不敏感）。"""
    exact = {name: name for name in columns}
    lower = {name.lower(): name for name in columns}
    for name in names:
        text = str(name or "").strip()
        if not text:
            continue
        if text in exact:
            return exact[text]
        hit = lower.get(text.lower())
        if hit:
            return hit
    return None


def _project_configured_column(project: dict | None) -> str:
    if not project:
        return ""
    uk = project.get("unique_key")
    if isinstance(uk, dict):
        return str(uk.get("column") or "").strip()
    if isinstance(uk, str):
        return uk.strip()
    return ""


def _etl_configured_column(project_id: str) -> str:
    pid = str(project_id or "").strip()
    if not pid:
        return ""
    try:
        from sqlalchemy import select

        from app.core.db import MetaSession
        from app.core.meta_init import init_meta_store
        from app.core.meta_models import MetaEtlModel

        init_meta_store()
        db = MetaSession()
        try:
            row = db.scalars(
                select(MetaEtlModel)
                .where(MetaEtlModel.project_id == pid)
                .limit(1)
            ).first()
            if row is None:
                return ""
            return str(row.unique_key or "").strip()
        finally:
            db.close()
    except Exception:
        return ""


def _system_configured_column() -> str:
    defaults = load_system_defaults()
    return str((defaults.get("unique_key") or {}).get("column") or "").strip()


def configured_sn_candidates(project: dict | None = None) -> list[str]:
    """按优先级列出「配置里写过的」SN 列名（去重保序）。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        text = str(name or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    add(_project_configured_column(project))
    if project:
        add(_etl_configured_column(str(project.get("project_id") or "")))
    add(_system_configured_column())
    return out


def pick_sn_column(
    columns: list[str], project: dict | None = None
) -> str | None:
    """从 raw 表列名中选出 SN / 唯一键列。"""
    cols = [str(c) for c in columns]
    if not cols:
        return None

    configured = configured_sn_candidates(project)
    hit = pick_col(cols, *configured, *_SN_ALIASES)
    if hit:
        return hit

    # 通配：任意 *CoverSN（BCoverSN / CCoverSN / DCoverSN…）
    for col in cols:
        if str(col).lower().endswith("coversn"):
            return col
    return None


def resolve_unique_key_name(project: dict | None = None) -> str:
    """仅解析配置名（不对照表结构），给入库/清洗默认值用。"""
    candidates = configured_sn_candidates(project)
    if candidates:
        return candidates[0]
    return "FCoverSN"
