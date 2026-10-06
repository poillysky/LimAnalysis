"""部门间人工通知：写入 meta，发送即落库。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.db import MetaSession
from app.core.meta_init import MANUAL_NOTICES_KEY, init_meta_store
from app.core.meta_models import MetaSetting

TZ = ZoneInfo("Asia/Shanghai")


def _session():
    init_meta_store()
    return MetaSession()


def _load_raw() -> list[dict]:
    db = _session()
    try:
        row = db.get(MetaSetting, MANUAL_NOTICES_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        notices = value.get("notices")
        return list(notices) if isinstance(notices, list) else []
    finally:
        db.close()


def _save_raw(notices: list[dict]) -> list[dict]:
    db = _session()
    try:
        payload = {"notices": notices}
        row = db.get(MetaSetting, MANUAL_NOTICES_KEY)
        if row is None:
            db.add(MetaSetting(key=MANUAL_NOTICES_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        return notices
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _next_id(notices: list[dict]) -> int:
    nums = []
    for item in notices:
        try:
            nums.append(int(item.get("id")))
        except (TypeError, ValueError):
            continue
    return (max(nums) + 1) if nums else 1


def _clean_recipient(raw: dict) -> dict | None:
    department = str(raw.get("department") or "").strip()
    name = str(raw.get("name") or "").strip()
    phone = str(raw.get("phone") or "").strip()
    if not department and not name and not phone:
        return None
    return {"department": department, "name": name, "phone": phone}


def _to_notice(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        notice_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    recipients = []
    for item in raw.get("recipients") or []:
        if isinstance(item, dict):
            cleaned = _clean_recipient(item)
            if cleaned:
                recipients.append(cleaned)
    return {
        "id": notice_id,
        "from_dept": str(raw.get("from_dept") or "").strip(),
        "topic": str(raw.get("topic") or "").strip(),
        "body": str(raw.get("body") or "").strip(),
        "recipients": recipients,
        "created_at": str(raw.get("created_at") or "").strip(),
    }


def list_manual_notices() -> dict:
    notices = []
    for item in _load_raw():
        notice = _to_notice(item)
        if notice:
            notices.append(notice)
    notices.sort(key=lambda row: (row.get("created_at") or "", row["id"]), reverse=True)
    return {"notices": notices}


def send_manual_notice(data: dict) -> dict:
    from_dept = str(data.get("from_dept") or "").strip()
    topic = str(data.get("topic") or "").strip()
    body = str(data.get("body") or "").strip()
    if not topic and not body:
        raise ValueError("请填写事项或正文")
    recipients = []
    for item in data.get("recipients") or []:
        if isinstance(item, dict):
            cleaned = _clean_recipient(item)
            if cleaned:
                recipients.append(cleaned)
    if not recipients:
        raise ValueError("请填写接收部门或人员")
    notices = _load_raw()
    notice = {
        "id": _next_id(notices),
        "from_dept": from_dept,
        "topic": topic or "部门沟通",
        "body": body,
        "recipients": recipients,
        "created_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
    }
    notices.append(notice)
    _save_raw(notices)
    saved = _to_notice(notice)
    if saved is None:
        raise RuntimeError("通知写入失败")
    return saved


def delete_manual_notice(notice_id: int) -> None:
    notices = _load_raw()
    kept = []
    found = False
    for item in notices:
        try:
            current = int(item.get("id"))
        except (TypeError, ValueError):
            kept.append(item)
            continue
        if current == notice_id:
            found = True
            continue
        kept.append(item)
    if not found:
        raise LookupError("通知不存在")
    _save_raw(kept)
