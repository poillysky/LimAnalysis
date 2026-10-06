import re
from pathlib import Path

FRONT = Path(r"E:\Project\LimAnalysis\frontend\src")


def script_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<script[^>]*>(.*?)</script>", text, re.S)
    return m.group(1) if m else ""


def strip_comments(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in "\"'`":
            q = c
            out.append(c)
            i += 1
            while i < n:
                out.append(s[i])
                if s[i] == "\\":
                    if i + 1 < n:
                        out.append(s[i + 1])
                        i += 2
                        continue
                elif s[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def norm(s: str) -> str:
    s = strip_comments(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_bodies(src: str, kw: str) -> dict:
    """kw='function' 抽函数声明，kw='const' 抽 const name = (...) => {...} / function 形式。"""
    out = {}
    for m in re.finditer(rf"^{kw}\s+(\w+)\s*", src, re.M):
        name = m.group(1)
        rest = src[m.end() :]
        rm = re.match(r"=\s*(?:async\s*)?", rest)
        if kw == "const":
            if not rm:
                continue
            rest = rest[rm.end() :]
            rest = re.sub(r"^function\s*", "", rest)
        pm = re.search(r"\(", rest)
        if not pm:
            continue
        depth = 0
        end_params = None
        for j in range(pm.start(), len(rest)):
            if rest[j] == "(":
                depth += 1
            elif rest[j] == ")":
                depth -= 1
                if depth == 0:
                    end_params = j
                    break
        if end_params is None:
            continue
        tail = rest[end_params + 1 :]
        tm = re.match(r"\s*(:\s*[^{]*?)?\s*=>\s*", tail)
        body_start = end_params + 1
        if tm:
            body_start += tm.end()
        bi = rest.find("{", body_start)
        if bi < 0:
            continue
        depth = 0
        for j in range(bi, len(rest)):
            if rest[j] == "{":
                depth += 1
            elif rest[j] == "}":
                depth -= 1
                if depth == 0:
                    line = src[: m.start()].count("\n") + 1
                    out[name] = (rest[bi : j + 1], line)
                    break
    return out


targets = [
    FRONT / "views/exception/cavity/index.vue",
    FRONT / "views/scan/analysis.vue",
    FRONT / "views/feature/etl.vue",
    FRONT / "views/feature/agg.vue",
    FRONT / "views/feature/sfc.vue",
    FRONT / "views/defect/analysis/index.vue",
    FRONT / "views/inspection/viewer.vue",
    FRONT / "views/feature/index.vue",
]

data = {}
for t in targets:
    s = script_of(t)
    fns = extract_bodies(s, "function")
    for k, v in extract_bodies(s, "const").items():
        fns.setdefault(k, v)
    data[t] = fns

print("=== 顶层函数/常量箭头函数数量（修正后） ===")
for t in targets:
    print(f"  {t.relative_to(FRONT)}: {len(data[t])}")

names = list(data)
print()
print("=== 跨文件真等价（完整函数体归一化一致） ===")
found_any = False
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        ta, tb = names[a], names[b]
        fa, fb = data[ta], data[tb]
        hits = []
        for k in sorted(set(fa) & set(fb)):
            if norm(fa[k][0]) == norm(fb[k][0]):
                na = fa[k][0].count("\n") + 1
                nb = fb[k][0].count("\n") + 1
                hits.append((k, fa[k][1], na, fb[k][1], nb))
        if hits:
            found_any = True
            print(f"\n--- {ta.relative_to(FRONT)}  <->  {tb.relative_to(FRONT)} ---")
            total = 0
            for k, la, na, lb, nb in hits:
                print(f"  {k:20s} L{la}({na}行)  <->  L{lb}({nb}行)")
                total += na
            print(f"  => {len(hits)} 个，去重可省约 {total} 行")
if not found_any:
    print("  （无）")

print()
print("=== 同名但不等价（同名≠同义，列反例风险） ===")
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        ta, tb = names[a], names[b]
        fa, fb = data[ta], data[tb]
        diffs = [k for k in sorted(set(fa) & set(fb)) if norm(fa[k][0]) != norm(fb[k][0])]
        if diffs:
            print(f"  {ta.name} <-> {tb.name}: {', '.join(diffs)}")
