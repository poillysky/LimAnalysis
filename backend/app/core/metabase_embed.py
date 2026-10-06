"""用连接管理里的 Metabase 账号签发静态嵌入 URL（开源版）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.connections import load_metabase
from app.core.projects import load_projects

_TIMEOUT = 20


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _jwt_hs256(payload: dict, secret: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(
        secret.encode(),
        f"{header}.{body}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def _call(base: str, method: str, path: str, token: str | None, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "LimAnalysis"}
    if token:
        headers["X-Metabase-Session"] = token
    req = Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw else raw
        except Exception:
            parsed = raw[:500]
        return exc.code, parsed
    except URLError as exc:
        return 0, str(exc.reason or exc)[:200]


def _login(base: str, username: str, password: str) -> str:
    code, payload = _call(
        base,
        "POST",
        "/api/session",
        None,
        {"username": username, "password": password},
    )
    if code >= 400 or not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("Metabase 登录失败，请到连接管理核对账号密码")
    return str(payload["id"])


def _setting_get(base: str, token: str, key: str):
    code, payload = _call(base, "GET", "/api/session/properties", token)
    if code < 400 and isinstance(payload, dict) and key in payload:
        return payload.get(key)
    code, payload = _call(base, "GET", f"/api/setting/{key}", token)
    if code >= 400:
        return None
    if isinstance(payload, dict) and "value" in payload:
        return payload.get("value")
    return payload


def _setting_put(base: str, token: str, key: str, value) -> None:
    _call(base, "PUT", f"/api/setting/{key}", token, {"value": value})


def _ensure_embedding(base: str, token: str) -> str:
    _setting_put(base, token, "enable-embedding", True)
    _setting_put(base, token, "enable-embedding-static", True)
    secret = _setting_get(base, token, "embedding-secret-key")
    if not secret:
        raise RuntimeError("无法读取 Metabase 嵌入密钥，请在 Metabase 管理后台打开静态嵌入")
    return str(secret)


def _list_dashboards(base: str, token: str) -> list[dict]:
    code, payload = _call(base, "GET", "/api/dashboard", token)
    if code < 400 and isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("dashboards") or []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    items: list[dict] = []
    code, root = _call(base, "GET", "/api/collection/root/items?models=dashboard", token)
    if isinstance(root, dict):
        for item in root.get("data") or []:
            if item.get("model") == "dashboard" or item.get("id"):
                items.append(item)
    code, cols = _call(base, "GET", "/api/collection", token)
    collections = cols if isinstance(cols, list) else (cols or {}).get("data") or []
    for col in collections:
        cid = col.get("id")
        if cid in (None, "root"):
            continue
        _, pack = _call(base, "GET", f"/api/collection/{cid}/items?models=dashboard", token)
        for item in (pack or {}).get("data") or [] if isinstance(pack, dict) else []:
            items.append(item)
    return items


def _norm(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _board_kind(name: str) -> str:
    raw = str(name or "")
    if "注塑" in raw:
        return "mold"
    if "自动外观" in raw or "外观" in raw:
        return "appearance"
    return "main"


def _board_label(kind: str, name: str) -> str:
    if kind == "mold":
        return "注塑机"
    if kind == "appearance":
        return "自动外观"
    return str(name or "综合")


def _match_dashboards(project: dict, dashboards: list[dict]) -> list[dict]:
    cfg = project.get("config") if isinstance(project.get("config"), dict) else {}
    wanted = cfg.get("metabase_dashboard_id")
    if wanted is not None:
        for item in dashboards:
            if str(item.get("id")) == str(wanted):
                return [item]
    keys = [
        _norm(project.get("display_name") or ""),
        _norm(project.get("prefix") or ""),
        _norm(project.get("project_id") or ""),
    ]
    keys = [k for k in keys if k]
    hits: list[tuple[int, dict]] = []
    for item in dashboards:
        name = _norm(item.get("name") or "")
        if not name:
            continue
        score = 0
        for key in keys:
            if key and key in name:
                score = max(score, len(key))
        if score:
            hits.append((score, item))
    hits.sort(key=lambda row: -row[0])
    seen: set[str] = set()
    out: list[dict] = []
    for _, item in hits:
        did = str(item.get("id") or "")
        if not did or did in seen:
            continue
        seen.add(did)
        out.append(item)
    return out


def _match_dashboard(project: dict, dashboards: list[dict]) -> dict | None:
    hits = _match_dashboards(project, dashboards)
    return hits[0] if hits else None


def _pick_dashboard(hits: list[dict], kind: str | None) -> dict | None:
    if not hits:
        return None
    tagged = [(_board_kind(str(item.get("name") or "")), item) for item in hits]
    if kind in {"appearance", "mold", "main"}:
        for k, item in tagged:
            if k == kind:
                return item
    for prefer in ("appearance", "main", "mold"):
        for k, item in tagged:
            if k == prefer:
                return item
    return hits[0]


def _enable_dashboard_embed(base: str, token: str, dashboard_id: int) -> None:
    code, current = _call(base, "GET", f"/api/dashboard/{dashboard_id}", token)
    if code >= 400 or not isinstance(current, dict):
        return
    if current.get("enable_embedding"):
        return
    _call(
        base,
        "PUT",
        f"/api/dashboard/{dashboard_id}",
        token,
        {
            "name": current.get("name"),
            "enable_embedding": True,
            "embedding_params": current.get("embedding_params") or {},
        },
    )


def board_for_project(project_id: str | None = None, board: str | None = None) -> dict:
    stored = load_metabase()
    base = str(stored.get("url") or "").rstrip("/")
    username = str(stored.get("username") or "").strip()
    password = str(stored.get("password") or "")
    projects = [p for p in load_projects() if p.get("enabled", True)]
    if not projects:
        return {
            "projects": [],
            "current": None,
            "error": "没有已启用的项目",
        }
    chosen = None
    if project_id:
        for item in projects:
            if item.get("project_id") == project_id:
                chosen = item
                break
        if chosen is None:
            return {
                "projects": _public_projects(projects, None),
                "current": None,
                "error": "项目不存在",
            }
    else:
        chosen = projects[0]
    summary = _public_projects(projects, None)
    empty_current = {
        "project_id": chosen["project_id"],
        "display_name": chosen["display_name"],
        "embed_url": "",
        "board": "",
        "boards": [],
    }
    if not base or not username or not password:
        return {
            "projects": summary,
            "current": empty_current,
            "error": "请先在连接管理填写 Metabase 地址和账号密码",
        }
    try:
        token = _login(base, username, password)
        secret = _ensure_embedding(base, token)
        dashboards = _list_dashboards(base, token)
        matched_map = {
            p["project_id"]: _match_dashboards(p, dashboards) for p in projects
        }
        summary = _public_projects(
            projects, {k: (v[0] if v else None) for k, v in matched_map.items()}
        )
        hits = matched_map.get(chosen["project_id"]) or []
        boards = []
        seen_kind: set[str] = set()
        for item in hits:
            kind = _board_kind(str(item.get("name") or ""))
            if kind in seen_kind:
                continue
            seen_kind.add(kind)
            boards.append(
                {
                    "kind": kind,
                    "label": _board_label(kind, str(item.get("name") or "")),
                    "name": item.get("name"),
                    "dashboard_id": item.get("id"),
                }
            )
        order = {"appearance": 0, "mold": 1, "main": 2}
        boards.sort(key=lambda row: order.get(str(row["kind"]), 9))
        dash = _pick_dashboard(hits, str(board or "").strip() or None)
        if not dash:
            return {
                "projects": summary,
                "current": {**empty_current, "boards": boards},
                "error": "该项目还没有 Metabase 画布，先在 Metabase 里建同名看板",
            }
        dash_id = int(dash["id"])
        kind = _board_kind(str(dash.get("name") or ""))
        _enable_dashboard_embed(base, token, dash_id)
        payload = {
            "resource": {"dashboard": dash_id},
            "params": {},
            "exp": int(time.time()) + 60 * 60,
        }
        jwt = _jwt_hs256(payload, secret)
        embed_url = (
            f"{base}/embed/dashboard/{jwt}"
            f"#bordered=false&titled=false&downloads=false"
        )
        return {
            "projects": summary,
            "current": {
                "project_id": chosen["project_id"],
                "display_name": chosen["display_name"],
                "embed_url": embed_url,
                "dashboard_id": dash_id,
                "board": kind,
                "boards": boards,
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "projects": summary,
            "current": empty_current,
            "error": str(exc)[:240],
        }


def _public_projects(projects: list[dict], matched: dict | None) -> list[dict]:
    out = []
    for item in projects:
        dash = (matched or {}).get(item["project_id"]) if matched else None
        out.append(
            {
                "project_id": item["project_id"],
                "display_name": item["display_name"],
                "has_board": bool(dash),
            }
        )
    return out
