"""中文描述 → 派生公式（车间常用说法，规则生成，无需外部大模型）。"""

from __future__ import annotations

import re
from typing import Any

# 前端快捷示例（也可由 API 返回）
PROMPT_EXAMPLES: list[dict[str, str]] = [
    {"label": "截取前几位", "prompt": "取 FCoverSN 前3位"},
    {"label": "截取后几位", "prompt": "取 FCoverSN 后4位"},
    {"label": "中间截取", "prompt": "从 FCoverSN 第4位起取6位"},
    {"label": "去空格", "prompt": "去掉 前盖码 两边空格"},
    {"label": "转大写", "prompt": "把 机台 转成大写"},
    {"label": "空值默认", "prompt": "线体 为空时填 未知"},
    {"label": "拼接两列", "prompt": "拼接 线体 和 工站，中间用横杠"},
    {"label": "OK/NG 转义", "prompt": "结果 为 OK 显示 合格，否则 不合格"},
    {"label": "0/1 转义", "prompt": "B2凹坑气泡 为 1 显示 不良，为 0 显示 良"},
    {
        "label": "有1为1",
        "prompt": "[A] [B] [C] 全空为空，有一个为1就是1，其他为0",
    },
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _quote_field(name: str) -> str:
    return f"[{name}]"


def _resolve_field(token: str, available: list[str]) -> str | None:
    """在可用字段里解析用户提到的列名。"""
    raw = str(token or "").strip().strip("[]`\"'")
    if not raw:
        return None
    if raw in available:
        return raw
    # 去序号后缀再比：线体1 → 线体
    for col in available:
        if col == raw or col.lower() == raw.lower():
            return col
    # 包含匹配（长的优先）
    candidates = [c for c in available if raw in c or c in raw]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    # 全文里找完整字段名
    return None


def _find_field_in_text(text: str, available: list[str]) -> str | None:
    if not text or not available:
        return None
    # 按长度降序，避免短名抢匹配
    for col in sorted(available, key=len, reverse=True):
        if col and col in text:
            return col
    # 英文不区分大小写
    lower_map = {c.lower(): c for c in available}
    for key, col in sorted(lower_map.items(), key=lambda x: len(x[0]), reverse=True):
        if key and key in text.lower():
            return col
    return None


def _eq_expr(col: str, value: str, *, source_kind: str) -> str:
    """生成等值比较；typed 下对 0/1 用数值比较。"""
    token = str(value or "").strip()
    if source_kind == "typed" and token in {"0", "1"}:
        return f"{_quote_field(col)} = {int(token)}"
    return (
        f"UPPER(TRIM({_quote_field(col)}::text)) = UPPER('{_esc(token)}')"
    )


def generate_formula_from_prompt(
    prompt: str,
    available_fields: list[str] | None = None,
    hint_field: str | None = None,
    *,
    source_kind: str = "raw",
) -> dict[str, Any]:
    """根据中文需求生成公式。

    source_kind=raw：RAW 文本；typed：已类型化 DWD。
    """
    text = str(prompt or "").strip()
    if not text:
        return {
            "ok": False,
            "formula": "",
            "explanation": "",
            "error": "请先用中文描述需求，例如：取 FCoverSN 前3位",
            "examples": PROMPT_EXAMPLES,
        }

    fields = [str(f).strip() for f in (available_fields or []) if str(f).strip()]
    hint = str(hint_field or "").strip() or None
    compact = _norm(text)
    kind = "typed" if str(source_kind or "").strip().lower() == "typed" else "raw"

    def field_or_hint(explicit: str | None = None) -> str | None:
        if explicit:
            resolved = _resolve_field(explicit, fields) if fields else explicit
            return resolved or explicit
        found = _find_field_in_text(text, fields)
        if found:
            return found
        if hint:
            return hint
        return fields[0] if len(fields) == 1 else None

    # 1) 前 N 位 / 左边 N 位
    m = re.search(
        r"(?:取|截取|拿)?\s*([A-Za-z0-9_\u4e00-\u9fff]+)?\s*(?:的)?\s*(?:前|左)\s*(\d+)\s*位",
        text,
    )
    if m or re.search(r"(前|左)\d+位", compact):
        if not m:
            m2 = re.search(r"(前|左)(\d+)位", text)
            n = int(m2.group(2)) if m2 else 3
            col = field_or_hint()
        else:
            col = field_or_hint(m.group(1))
            n = int(m.group(2))
        if not col:
            return _need_field(text, "取某列前N位")
        formula = f"LEFT({_quote_field(col)}, {n})"
        return _ok(formula, f"从「{col}」截取左边 {n} 个字符", fields)

    # 2) 后 N 位
    m = re.search(
        r"(?:取|截取|拿)?\s*([A-Za-z0-9_\u4e00-\u9fff]+)?\s*(?:的)?\s*(?:后|右)\s*(\d+)\s*位",
        text,
    )
    if m or re.search(r"(后|右)\d+位", compact):
        if not m:
            m2 = re.search(r"(后|右)(\d+)位", text)
            n = int(m2.group(2)) if m2 else 3
            col = field_or_hint()
        else:
            col = field_or_hint(m.group(1))
            n = int(m.group(2))
        if not col:
            return _need_field(text, "取某列后N位")
        formula = f"RIGHT({_quote_field(col)}, {n})"
        return _ok(formula, f"从「{col}」截取右边 {n} 个字符", fields)

    # 3) 从第 M 位起取 N 位
    m = re.search(
        r"(?:从)?\s*([A-Za-z0-9_\u4e00-\u9fff]+)?\s*(?:的)?\s*第\s*(\d+)\s*位\s*(?:起|开始)?\s*(?:取|截)?\s*(\d+)\s*位",
        text,
    )
    if m:
        col = field_or_hint(m.group(1))
        start, length = int(m.group(2)), int(m.group(3))
        if not col:
            return _need_field(text, "从第M位起取N位")
        formula = f"SUBSTRING({_quote_field(col)} FROM {start} FOR {length})"
        return _ok(formula, f"从「{col}」第 {start} 位起取 {length} 位", fields)

    # 4) 去空格
    if (
        any(k in compact for k in ("去空格", "去掉空格", "去除空格", "trim", "去空"))
        or ("空格" in compact and any(k in compact for k in ("去掉", "去除", "去掉两边", "去两边")))
    ):
        col = field_or_hint()
        if not col:
            return _need_field(text, "去掉某列空格")
        formula = f"TRIM({_quote_field(col)})"
        return _ok(formula, f"去掉「{col}」首尾空格", fields)

    # 5) 大小写
    if any(k in compact for k in ("转大写", "大写", "upper")):
        col = field_or_hint()
        if not col:
            return _need_field(text, "转大写")
        return _ok(f"UPPER({_quote_field(col)})", f"「{col}」转为大写", fields)
    if any(k in compact for k in ("转小写", "小写", "lower")):
        col = field_or_hint()
        if not col:
            return _need_field(text, "转小写")
        return _ok(f"LOWER({_quote_field(col)})", f"「{col}」转为小写", fields)

    # 6) 空则默认
    m = re.search(
        r"([A-Za-z0-9_\u4e00-\u9fff]+)\s*(?:为空|是空|空值|没有值)?\s*(?:时|则)?\s*(?:填|默认|改成|写成|用)\s*[「『\"']?([^「」『』\"'\s]+)[」』\"']?",
        text,
    )
    if m and any(k in compact for k in ("为空", "空则", "默认", "空时", "没有值")):
        col = field_or_hint(m.group(1))
        default = m.group(2)
        if not col:
            return _need_field(text, "空值填默认")
        token = str(default or "").strip()
        if kind == "typed":
            fill = token if token in {"0", "1"} else f"'{_esc(token)}'"
            formula = f"COALESCE({_quote_field(col)}, {fill})"
        else:
            formula = (
                f"COALESCE(NULLIF(TRIM({_quote_field(col)}), ''), '{_esc(token)}')"
            )
        return _ok(formula, f"「{col}」为空时填「{token}」", fields)

    # 7) 拼接
    if "拼接" in compact or "连接" in compact:
        m = re.search(
            r"(?:拼接|连接)\s*([A-Za-z0-9_\u4e00-\u9fff]+)\s*(?:和|与|,|，)\s*([A-Za-z0-9_\u4e00-\u9fff]+)",
            text,
        )
        if m:
            a = field_or_hint(m.group(1))
            b = _resolve_field(m.group(2), fields) if fields else m.group(2)
        else:
            found = [
                c
                for c in sorted(fields, key=len, reverse=True)
                if c and c in text
            ]
            seen: list[str] = []
            for c in found:
                if c not in seen:
                    seen.append(c)
            if len(seen) < 2:
                return {
                    "ok": False,
                    "formula": "",
                    "explanation": "",
                    "error": "拼接请写清两列，例如：拼接 线体 和 工站，中间用横杠",
                    "examples": PROMPT_EXAMPLES,
                }
            a, b = seen[0], seen[1]
        if not a or not b:
            return _need_field(text, "拼接两列")
        if "横杠" in compact or "减号" in compact or "中划线" in compact:
            sep = "-"
        elif "下划线" in compact:
            sep = "_"
        elif "斜杠" in compact:
            sep = "/"
        else:
            sep = ""
        if sep:
            formula = f"{_quote_field(a)} || '{_esc(sep)}' || {_quote_field(b)}"
            explain = f"拼接「{a}」与「{b}」，中间「{sep}」"
        else:
            formula = f"{_quote_field(a)} || {_quote_field(b)}"
            explain = f"直接拼接「{a}」与「{b}」"
        return _ok(formula, explain, fields)

    # 8) 多列固定：全空→空；任一为 1→1；否则 0（2～5 列）
    if (
        ("全空" in compact and "为空" in compact)
        or "有一个为1" in compact
        or "有1为1" in compact
        or "任一为1" in compact
    ):
        cols: list[str] = []
        for name in re.findall(r"\[([^\]]+)\]", text):
            resolved = _resolve_field(name, fields) if fields else name.strip()
            if resolved and resolved not in cols:
                cols.append(resolved)
        if len(cols) < 2:
            for c in sorted(fields, key=len, reverse=True):
                if c and c in text and c not in cols:
                    cols.append(c)
        if len(cols) < 2:
            return {
                "ok": False,
                "formula": "",
                "explanation": "",
                "error": "请先写入 2～5 个字段，例如：[A] [B] [C] 全空为空，有一个为1就是1，其他为0",
                "examples": PROMPT_EXAMPLES,
            }
        if len(cols) > 5:
            return {
                "ok": False,
                "formula": "",
                "explanation": "",
                "error": "最多支持 5 个字段",
                "examples": PROMPT_EXAMPLES,
            }

        def _empty_expr(col: str) -> str:
            return f"(NULLIF(TRIM(CAST({_quote_field(col)} AS TEXT)), '') IS NULL)"

        def _one_expr(col: str) -> str:
            return f"NULLIF(TRIM(CAST({_quote_field(col)} AS TEXT)), '') = '1'"

        formula = (
            f"CASE WHEN {' AND '.join(_empty_expr(c) for c in cols)} THEN NULL "
            f"WHEN {' OR '.join(_one_expr(c) for c in cols)} THEN 1 ELSE 0 END"
        )
        return _ok(
            formula,
            f"「{'、'.join(cols)}」全空→空；任一为1→1；否则→0",
            fields,
        )

    # 9) 多条件：A 为 x 显示 p，为 y 显示 q
    multi = list(
        re.finditer(
            r"为\s*[「『\"']?([^「」『』\"'，,\s]+)[」』\"']?\s*(?:时)?\s*"
            r"(?:显示|则|写成|改为)\s*[「『\"']?([^「」『』\"'，,\s]+)[」』\"']?",
            text,
        )
    )
    else_m = re.search(
        r"(?:否则|不然|其它|其他)\s*(?:显示|则|写成|改为)?\s*[「『\"']?([^「」『』\"'\s]+)[」』\"']?",
        text,
    )
    if len(multi) >= 1 and ("显示" in compact or "写成" in compact or "改为" in compact):
        col = field_or_hint(_find_field_in_text(text, fields))
        # 列名常在第一个「为」之前
        if not col:
            head = text[: multi[0].start()]
            col = field_or_hint(_find_field_in_text(head, fields) or hint)
        if not col:
            return _need_field(text, "条件转换")
        def _then_lit(value: str) -> str:
            token = str(value or "").strip()
            if kind == "typed" and token in {"0", "1"}:
                return token
            return f"'{_esc(token)}'"

        if len(multi) >= 2:
            parts = []
            for mm in multi:
                parts.append(
                    f"WHEN {_eq_expr(col, mm.group(1), source_kind=kind)} "
                    f"THEN {_then_lit(mm.group(2))}"
                )
            else_v = else_m.group(1) if else_m else None
            else_part = _then_lit(else_v) if else_v else _quote_field(col)
            formula = f"CASE {' '.join(parts)} ELSE {else_part} END"
            pairs = "；".join(f"{mm.group(1)}→{mm.group(2)}" for mm in multi)
            return _ok(formula, f"「{col}」：{pairs}", fields)
        when_v, then_v = multi[0].group(1), multi[0].group(2)
        else_v = else_m.group(1) if else_m else None
        else_part = _then_lit(else_v) if else_v else _quote_field(col)
        formula = (
            f"CASE WHEN {_eq_expr(col, when_v, source_kind=kind)} "
            f"THEN {_then_lit(then_v)} ELSE {else_part} END"
        )
        explain = (
            f"「{col}」为 {when_v} 时显示 {then_v}"
            + (f"，否则 {else_v}" if else_v else "，否则保持原值")
        )
        return _ok(formula, explain, fields)

    # 10) 直接像公式：已含 LEFT( / [字段]
    if re.search(r"\b(LEFT|RIGHT|TRIM|UPPER|LOWER|SUBSTRING|CASE|COALESCE)\b", text, re.I) or (
        "[" in text and "]" in text
    ):
        return _ok(text.strip(), "已按你写的表达式采用（请确认字段名用 [列名]）", fields)

    return {
        "ok": False,
        "formula": "",
        "explanation": "",
        "error": (
            "没识别出这种说法。可以试试："
            "「取 FCoverSN 前3位」「线体 为空时填 未知」"
            "「结果 为 OK 显示 合格，否则 不合格」"
        ),
        "examples": PROMPT_EXAMPLES,
        "available_fields": fields[:40],
    }


def _esc(value: str) -> str:
    return str(value).replace("'", "''")


def _ok(formula: str, explanation: str, fields: list[str]) -> dict[str, Any]:
    return {
        "ok": True,
        "formula": formula,
        "explanation": explanation,
        "error": "",
        "examples": PROMPT_EXAMPLES,
        "available_fields": fields[:40],
        "suggest_level": 2 if _refs_other_derived(formula, fields) else 1,
    }


def _refs_other_derived(formula: str, fields: list[str]) -> bool:
    # 简单启发：公式引用了不在原表字段里的名字时建议 L2（由调用方结合清洗列判断）
    return False


def _need_field(prompt: str, intent: str) -> dict[str, Any]:
    return {
        "ok": False,
        "formula": "",
        "explanation": "",
        "error": f"「{intent}」需要指明原表字段名，例如把列名写进描述里",
        "examples": PROMPT_EXAMPLES,
    }


def list_formula_help() -> dict[str, Any]:
    return {
        "examples": PROMPT_EXAMPLES,
        "tips": [
            "字段请用中文名或英文名直接写在句子里，生成后会变成 [字段名]",
            "清洗页：源表是 RAW 文本；聚合页：源表是已类型化的 DWD（0/1 用数值比较）",
            "支持：截取前后位、中间截取、去空格、大小写、空值默认、拼接、OK/NG 或 0/1 转义",
            "若引用的是本页其它清洗列，请把派生层级设为 L2",
        ],
    }
