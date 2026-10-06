"""OpenAI 兼容 Chat Completions 客户端。"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.core.ai_config import get_ai_api_key, load_ai_config_public, load_ai_config_raw
from app.core.sql_ident import is_safe_sql_expression


def _base_v1(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base[: -len("/chat/completions")]
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _chat_url(base_url: str) -> str:
    return f"{_base_v1(base_url)}/chat/completions"


def _models_url(base_url: str) -> str:
    return f"{_base_v1(base_url)}/models"


def _friendly_http_error(status: int, detail: str, *, model: str = "") -> str:
    text = str(detail or "")
    low = text.lower()
    if status == 404 or "model_not_found" in low or "model not found" in low:
        tip = f"模型「{model}」在当前接口不存在。" if model else "模型不存在。"
        return (
            f"{tip}请核对模型名是否与服务商一致，"
            f"或点「拉取模型列表」从接口选择。原始信息：{text[:240]}"
        )
    if status in (401, 403) or "invalid_api_key" in low or "authentication" in low:
        return f"鉴权失败，请检查 API Key。原始信息：{text[:240]}"
    return f"HTTP {status}: {text[:320]}"


def chat_completion(
    *,
    messages: list[dict[str, str]],
    temperature: float | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """调用已配置的 AI；返回 {ok, content|error, raw?}。"""
    public = load_ai_config_public()
    if not public.get("ready"):
        return {
            "ok": False,
            "error": "AI 未就绪：请到「AI模型配置」填写地址、模型与 API Key，并启用",
        }

    raw = load_ai_config_raw()
    api_key = get_ai_api_key()
    if not api_key:
        return {"ok": False, "error": "API Key 未设置"}

    url = _chat_url(str(raw.get("base_url") or ""))
    model = str(raw.get("model") or "").strip()
    temp = (
        float(temperature)
        if temperature is not None
        else float(raw.get("temperature") or 0.2)
    )
    to = int(timeout if timeout is not None else raw.get("timeout_seconds") or 45)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=to)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"请求失败: {exc}"}

    if resp.status_code >= 400:
        detail = resp.text[:400]
        try:
            err = resp.json()
            detail = str(
                (err.get("error") or {}).get("message")
                or err.get("message")
                or detail
            )
        except Exception:
            pass
        return {
            "ok": False,
            "error": _friendly_http_error(resp.status_code, detail, model=model),
        }

    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "响应不是 JSON"}

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "响应缺少 choices.message.content", "raw": data}

    return {"ok": True, "content": str(content or "").strip(), "raw": data}


def test_ai_connection() -> dict[str, Any]:
    result = chat_completion(
        messages=[
            {
                "role": "user",
                "content": 'Reply with exactly: {"ok":true}',
            }
        ],
        temperature=0,
        timeout=30,
    )
    if not result.get("ok"):
        return {"ok": False, "message": result.get("error") or "连接失败"}
    return {
        "ok": True,
        "message": "连接成功",
        "reply": (result.get("content") or "")[:200],
    }


def list_ai_models() -> dict[str, Any]:
    """拉取 OpenAI 兼容 /models 列表，便于纠正 Model not found。"""
    public = load_ai_config_public()
    raw = load_ai_config_raw()
    api_key = get_ai_api_key()
    base = str(raw.get("base_url") or "").strip()
    if not base:
        return {"ok": False, "error": "请先填写接口地址", "models": []}
    # Ollama 常无 key；其它服务一般需要
    if not api_key and "11434" not in base and not public.get("api_key_set"):
        return {"ok": False, "error": "请先填写并保存 API Key", "models": []}

    url = _models_url(base)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    to = min(30, int(raw.get("timeout_seconds") or 45))
    try:
        resp = requests.get(url, headers=headers, timeout=to)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"拉取失败: {exc}", "models": []}

    if resp.status_code >= 400:
        detail = resp.text[:300]
        try:
            err = resp.json()
            detail = str(
                (err.get("error") or {}).get("message")
                or err.get("message")
                or detail
            )
        except Exception:
            pass
        return {
            "ok": False,
            "error": _friendly_http_error(resp.status_code, detail),
            "models": [],
        }

    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "模型列表不是 JSON", "models": []}

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        # 少数实现直接返回 list
        items = data if isinstance(data, list) else []

    models: list[str] = []
    for item in items:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or "").strip()
        else:
            name = ""
        if name and name not in models:
            models.append(name)
    models.sort(key=str.lower)
    current = str(raw.get("model") or "").strip()
    return {
        "ok": True,
        "models": models,
        "current": current,
        "current_found": bool(current and current in models),
        "message": f"共 {len(models)} 个模型"
        + (
            ""
            if not current or current in models
            else f"；当前「{current}」不在列表中，请改选"
        ),
    }


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def parse_json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    # 去掉 ```json ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = _JSON_BLOCK.search(raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def generate_etl_formula_with_ai(
    prompt: str,
    available_fields: list[str] | None = None,
    hint_field: str | None = None,
    *,
    source_kind: str = "raw",
) -> dict[str, Any]:
    """用 AI 根据中文需求生成派生公式。

    source_kind:
      - raw：清洗，读 lim_raw（TEXT）
      - typed：聚合等，读已类型化的 DWD（timestamptz/smallint/numeric）
    """
    fields = [str(f).strip() for f in (available_fields or []) if str(f).strip()]
    field_list = "、".join(fields[:80]) if fields else "（未提供，请从描述推断）"
    hint = str(hint_field or "").strip()
    kind = "typed" if str(source_kind or "").strip().lower() == "typed" else "raw"

    common = (
        "根据用户中文需求，生成可在 PostgreSQL SELECT 中使用的派生表达式。\n"
        "输出：只返回 JSON，不要 markdown。格式："
        '{"formula":"...","explanation":"一句话中文说明","derive_level":1或2}\n'
        "硬性规则：\n"
        "1. 字段引用必须写成 [字段名]，例如 LEFT([FCoverSN], 3)；不要用反引号。\n"
        "2. 可用：LEFT/RIGHT/SUBSTRING/TRIM/UPPER/LOWER/COALESCE/NULLIF/CONCAT/||/CASE WHEN；"
        "禁止 DROP/DELETE/INSERT/UPDATE/ALTER/分号/注释。\n"
        "3. 只引用源表字段 → derive_level=1；引用其它派生列结果 → 2。\n"
        "4. 描述里出现的 [字段] 必须原样用在公式里，不要擅自改名或漏列；"
        "不要发明用户未提到的字段。\n"
        "5. explanation 必须用正确简体中文，勿错别字。"
        "空值说「为空/全空」，不要写成「力空」等形近误字。\n"
    )
    if kind == "typed":
        system = (
            "你是车间聚合/类型化表公式助手。源表是已清洗的 DWD："
            "时间 timestamptz、布尔/点检 smallint(0/1)、产量不良 numeric/bigint、维度 text。\n"
            + common
            + "类型化表写法（必须遵守）：\n"
            "A. 判空用 IS NULL；不要对数值/布尔做 BTRIM(::text) 空串套路。\n"
            "B. 布尔/点检比较写成 = 1 / = 0；输出用 1 / 0 / NULL，不要文本 '1'/'0'。\n"
            "C. 文本维度才用 TRIM/UPPER/LEFT/RIGHT；时间列直接比较或 date_trunc。\n"
            "D. 不良率用 SUM(不良)/NULLIF(SUM(产量),0)，不要对小时率再 AVG。\n"
            "E. 多列「任一为1」示例："
            "CASE WHEN [A] IS NULL AND [B] IS NULL THEN NULL "
            "WHEN [A] = 1 OR [B] = 1 THEN 1 ELSE 0 END\n"
        )
    else:
        system = (
            "你是车间 ETL 清洗公式助手。源表是 lim_raw，列多为 TEXT。\n"
            + common
            + "原始文本表写法（必须遵守）：\n"
            "A. 判空不要只写 IS NULL；空串、空白、'nan'/'NaN'/'None'/'null' 也算空。"
            "统一用 NULLIF(CASE WHEN lower(BTRIM([字段]::text)) IN "
            "('nan','none','null','nat') THEN NULL ELSE BTRIM([字段]::text) END, '')；"
            "需要默认值再套 COALESCE(..., '默认')。\n"
            "B. 布尔/点检取值常为 '0'/'1'/'OK'/'NG'。比较前先按 A 判空，"
            "需要时 UPPER；比较写成 = '1' / = '0' / = 'OK'。\n"
            "C. CASE 条件按用户优先级；「任一为1」用 OR；"
            "「全空」用各列按 A 判空后均为 NULL，THEN NULL。不要把全空写成 '0'。\n"
            "D. 用户说「输出空」用 NULL；说输出 0/1/文字时用 '0'/'1'/... 文本字面量"
            "（写入时系统会按 field_type 收到 smallint/numeric）。\n"
            "E. 多列合并示例："
            "CASE WHEN NULLIF(TRIM([A]::text),'') IS NULL AND NULLIF(TRIM([B]::text),'') IS NULL "
            "THEN NULL WHEN NULLIF(TRIM([A]::text),'')='1' OR NULLIF(TRIM([B]::text),'')='1' "
            "THEN '1' ELSE '0' END\n"
        )
    user = (
        f"可用字段：{field_list}\n"
        + (f"当前行提示字段：{hint}\n" if hint else "")
        + f"需求：{prompt.strip()}"
    )
    result = chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    if not result.get("ok"):
        return {
            "ok": False,
            "formula": "",
            "explanation": "",
            "error": result.get("error") or "AI 生成失败",
            "source": "ai",
        }

    parsed = parse_json_object(str(result.get("content") or ""))
    if not parsed or not str(parsed.get("formula") or "").strip():
        return {
            "ok": False,
            "formula": "",
            "explanation": "",
            "error": "AI 返回无法解析，请改写描述或改用规则生成",
            "source": "ai",
            "raw_content": (result.get("content") or "")[:500],
        }

    formula = str(parsed.get("formula") or "").strip()
    explanation = _polish_explanation(str(parsed.get("explanation") or "").strip())
    level = int(parsed.get("derive_level") or 1)
    if level not in (1, 2):
        level = 1

    if not is_safe_sql_expression(formula):
        return {
            "ok": False,
            "formula": "",
            "explanation": "",
            "error": "AI 生成的公式未通过安全校验",
            "source": "ai",
        }

    return {
        "ok": True,
        "formula": formula,
        "explanation": explanation or "由 AI 生成",
        "error": "",
        "source": "ai",
        "suggest_level": level,
    }


def _polish_explanation(text: str) -> str:
    """修正说明里的常见形近/音近错字（长词优先）。"""
    if not text:
        return text
    fixes = (
        ("两列均为力空", "两列均为空"),
        ("均为力空", "均为空"),
        ("全为力空", "全为空"),
        ("全力空", "全为空"),
        ("力空", "为空"),
    )
    out = text
    for bad, good in fixes:
        out = out.replace(bad, good)
    return out
