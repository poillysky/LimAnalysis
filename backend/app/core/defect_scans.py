"""次品扫码：次品名称仍存 meta；扫码/文件明细写入 Postgres 次品库。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.defect_store import insert_upload, query_analysis
from app.core.defect_store import list_ops as list_pg_ops
from app.core.meta_init import (
    DEFECT_ANALYSIS_ALERT_KEY,
    DEFECT_SCAN_ITEMS_KEY,
    init_meta_store,
)
from app.core.meta_models import MetaSetting
from app.core.projects import get_project, load_projects

# 旧版曾把 ADS 模穴列名填进扫码下拉；配置只保留用户自己加的名称。
_LEGACY_SCAN_PRESETS = frozenset(
    {
        "B5合模线溢胶",
        "B1缺胶气泡",
        "B2凹坑",
        "底涂",
        "硅胶",
        "定位",
    }
)


def _session():
    init_meta_store()
    return MetaSession()


def _load_item_map() -> dict[str, list[str]]:
    db = _session()
    try:
        row = db.get(MetaSetting, DEFECT_SCAN_ITEMS_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        raw = value.get("projects")
        if not isinstance(raw, dict):
            return {}
        out: dict[str, list[str]] = {}
        dirty = False
        for pid, names in raw.items():
            key = str(pid or "").strip()
            if not key or not isinstance(names, list):
                continue
            cleaned = []
            seen: set[str] = set()
            for name in names:
                text = str(name or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                cleaned.append(text)
            if set(cleaned) == _LEGACY_SCAN_PRESETS:
                cleaned = []
                dirty = True
            out[key] = cleaned
        if dirty:
            payload = {"projects": out}
            if row is None:
                db.add(MetaSetting(key=DEFECT_SCAN_ITEMS_KEY, value=payload))
            else:
                row.value = payload
            db.commit()
        return out
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _save_item_map(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    db = _session()
    try:
        payload = {"projects": mapping}
        row = db.get(MetaSetting, DEFECT_SCAN_ITEMS_KEY)
        if row is None:
            db.add(MetaSetting(key=DEFECT_SCAN_ITEMS_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        return mapping
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_scan_projects() -> list[dict]:
    return [
        {"project_id": p["project_id"], "display_name": p["display_name"]}
        for p in load_projects()
        if p.get("enabled", True)
    ]


def list_defect_options(project_id: str) -> list[dict]:
    names = _load_item_map().get(str(project_id or "").strip()) or []
    return [{"key": name, "label": name} for name in names]


def load_project_items(project_id: str) -> dict:
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("请选择项目")
    if get_project(pid) is None:
        raise ValueError("项目不存在")
    return {
        "project_id": pid,
        "items": [d["key"] for d in list_defect_options(pid)],
        "projects": list_scan_projects(),
    }


def save_project_items(project_id: str, items: list[str]) -> dict:
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("请选择项目")
    if get_project(pid) is None:
        raise ValueError("项目不存在")
    cleaned = []
    seen: set[str] = set()
    for name in items or []:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        if len(text) > 80:
            raise ValueError("次品名称过长")
        seen.add(text)
        cleaned.append(text)
    mapping = _load_item_map()
    mapping[pid] = cleaned
    _save_item_map(mapping)
    return {"project_id": pid, "items": cleaned}


def bootstrap(project_id: str | None = None) -> dict:
    projects = list_scan_projects()
    current_id = str(project_id or "").strip()
    if current_id and not any(p["project_id"] == current_id for p in projects):
        raise ValueError("项目不存在")
    if not current_id and projects:
        current_id = projects[0]["project_id"]
    defects = list_defect_options(current_id) if current_id else []
    return {
        "projects": projects,
        "current_id": current_id,
        "defects": defects,
    }


_SN_HEADERS = {"sn", "二维码", "条码", "序列号", "fcoversn", "code"}
_BATCH_LIMIT = 2000


def _prepare_scan(project_id: str, defect_item: str) -> tuple[str, str, dict]:
    pid = str(project_id or "").strip()
    item = str(defect_item or "").strip()
    if not pid:
        raise ValueError("请选择项目")
    if not item:
        raise ValueError("请选择次品项")
    project = get_project(pid)
    if project is None or not project.get("enabled", True):
        raise ValueError("项目不存在")
    allowed = {d["key"] for d in list_defect_options(pid)}
    if not allowed:
        raise ValueError("请先在功能管理配置该项目的次品名称")
    if item not in allowed:
        raise ValueError("次品项不在当前项目配置中")
    return pid, item, project


def _clean_sns(sns: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in sns or []:
        code = str(raw or "").strip()
        if not code or code in seen:
            continue
        if len(code) > 120:
            raise ValueError("SN 过长")
        seen.add(code)
        cleaned.append(code)
    if not cleaned:
        raise ValueError("没有可上传的 SN")
    if len(cleaned) > _BATCH_LIMIT:
        raise ValueError(f"单次最多 {_BATCH_LIMIT} 条")
    return cleaned


def _insert_scans(
    pid: str,
    item: str,
    project: dict,
    sns: list[str],
    method: str,
) -> dict:
    codes = _clean_sns(sns)
    return insert_upload(
        project=project,
        defect_item=item,
        method=method,
        sns=codes,
    )


def record_scan(project_id: str, defect_item: str, sn: str) -> dict:
    pid, item, project = _prepare_scan(project_id, defect_item)
    return _insert_scans(pid, item, project, [sn], "scan")


def record_scans(
    project_id: str,
    defect_item: str,
    sns: list[str],
    method: str = "scan",
) -> dict:
    pid, item, project = _prepare_scan(project_id, defect_item)
    return _insert_scans(pid, item, project, sns, method)


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _sns_from_frame(frame) -> list[str]:
    if frame is None or getattr(frame, "empty", True):
        return []
    columns = [str(col).strip() for col in frame.columns]
    lower = [col.lower().replace(" ", "") for col in columns]
    pick = 0
    for index, name in enumerate(lower):
        if name in _SN_HEADERS or "二维码" in columns[index] or "条码" in columns[index]:
            pick = index
            break
    values = []
    for raw in frame.iloc[:, pick].tolist():
        text = str(raw or "").strip()
        if not text or text.lower() in _SN_HEADERS:
            continue
        values.append(text)
    return values


def parse_sn_file(filename: str, content: bytes) -> list[str]:
    name = str(filename or "").lower()
    if not content:
        raise ValueError("文件是空的")
    if name.endswith((".xlsx", ".xls")):
        from io import BytesIO

        import pandas as pd

        try:
            frame = pd.read_excel(BytesIO(content), dtype=str)
        except ImportError as exc:
            raise ValueError("Excel 需要 openpyxl，或把文件另存为 CSV") from exc
        sns = _sns_from_frame(frame)
        if not sns:
            raise ValueError("表格里没有读到 SN")
        return sns
    text = _decode_bytes(content)
    first = next((line for line in text.splitlines() if line.strip()), "")
    if name.endswith(".csv") or "," in first:
        from io import StringIO

        import pandas as pd

        frame = pd.read_csv(StringIO(text), dtype=str)
        sns = _sns_from_frame(frame)
        if sns:
            return sns
    sns = []
    for line in text.splitlines():
        part = line.split(",")[0].split("\t")[0].strip().strip('"')
        if not part or part.lower().replace(" ", "") in _SN_HEADERS:
            continue
        sns.append(part)
    if not sns:
        raise ValueError("文件里没有读到 SN")
    return sns


def import_sn_file(project_id: str, defect_item: str, filename: str, content: bytes) -> dict:
    return record_scans(
        project_id,
        defect_item,
        parse_sn_file(filename, content),
        method="file",
    )


def list_ops(
    *,
    project_id: str | None = None,
    defect_item: str | None = None,
    limit: int = 200,
) -> dict:
    return list_pg_ops(
        project_id=project_id,
        defect_item=defect_item,
        limit=limit,
    )


def query_defect_analysis(
    project_id: str,
    *,
    hours: int = 12,
    defect_item: str | None = None,
    exclude_machine_cavities=None,
    exclude_body_cavities=None,
) -> dict:
    pid = str(project_id or "").strip()
    if not pid:
        raise ValueError("请选择项目")
    if get_project(pid) is None:
        raise ValueError("项目不存在")
    return query_analysis(
        pid,
        hours=hours,
        defect_item=defect_item,
        exclude_machine_cavities=exclude_machine_cavities,
        exclude_body_cavities=exclude_body_cavities,
    )


def load_analysis_alert_rules() -> dict:
    from app.core.yield_alerts import _normalize_rules

    db = _session()
    try:
        row = db.get(MetaSetting, DEFECT_ANALYSIS_ALERT_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        return _normalize_rules(value)
    finally:
        db.close()


def save_analysis_alert_rules(data: dict) -> dict:
    from app.core.yield_alerts import _normalize_rules

    rules = _normalize_rules(data)
    db = _session()
    try:
        row = db.get(MetaSetting, DEFECT_ANALYSIS_ALERT_KEY)
        if row is None:
            db.add(MetaSetting(key=DEFECT_ANALYSIS_ALERT_KEY, value=rules))
        else:
            row.value = rules
        db.commit()
        return rules
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
