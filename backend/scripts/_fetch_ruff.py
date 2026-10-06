"""下载 ruff 的 Windows 独立二进制并安装到 .venv/Scripts/。

## 为什么不用 pip

本机 `pip.ini` 配了 `proxy = http://127.0.0.1:7897`，但 WorkBuddy 注入的环境变量
`HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:61513` 会**覆盖**它，指向一个不通的
沙箱代理。结果是 pip 静默挂起或 SSLEOFError。curl 走 7897 能通，但 Windows
schannel 在大传输末尾会握手失败 / 截断（exit 35 / 124）。

所以这里用 Python 的 urllib 显式指定 7897，并实现：

1. **按版本查元数据**（`/pypi/ruff/<ver>/json`，几十 KB），
   而不是 `/pypi/ruff/json`（3.3MB 全量索引）—— 后者正是「下载很慢」的主因。
2. **断点续传**：用 HTTP `Range` 头从已下载字节处继续。代理掐断连接不会丢进度，
   重试即可累加，多轮之后必然拿全。
3. **sha256 校验**：对不上就删掉重来，不安装来路不明的二进制。

用法：
    python scripts/_fetch_ruff.py                # 装最新版
    python scripts/_fetch_ruff.py --version 0.16.10
    python scripts/_fetch_ruff.py --check        # 只报告状态
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
STAGE = BACKEND / ".tmpdl"
TARGET_EXE = BACKEND / ".venv" / "Scripts" / "ruff.exe"

# 优先用用户自己的代理 —— WorkBuddy 注入的 61513 在本机不通
DEFAULT_PROXY = "http://127.0.0.1:7897"
PROXY = os.environ.get("LIM_HTTP_PROXY", DEFAULT_PROXY)

# 默认钉一个已知可用版本。
# 刻意**不**默认去查「最新版」：那要拉 https://pypi.org/pypi/ruff/json（3.3MB，
# 含所有历史版本 × 所有平台），本机代理会在末尾掐断它。改为查
# /pypi/ruff/<ver>/json，只有几十 KB，稳定得多。要升级就显式传 --version。
PINNED_VERSION = "0.16.10"

MAX_ROUNDS = 40
CHUNK = 128 * 1024


def opener() -> urllib.request.OpenerDirector:
    """显式走代理。若代理不可用则回退直连，两者都试。"""
    handlers: list[urllib.request.BaseHandler] = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    ctx = ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def get_json(op: urllib.request.OpenerDirector, url: str, *, tries: int = 6) -> dict:
    last: Exception | None = None
    for i in range(tries):
        try:
            with op.open(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(0.8 * (i + 1))
    raise SystemExit(f"取元数据失败（{tries} 次）：{type(last).__name__}: {last}")


def pick_wheel(meta: dict, version: str) -> tuple[str, int, str]:
    for item in meta["urls"]:
        if item["filename"].endswith("win_amd64.whl"):
            return item["url"], item["size"], item["digests"]["sha256"]
    names = [i['filename'] for i in meta['urls']]
    raise SystemExit(f"ruff {version} 没有 win_amd64 wheel：{names}")


def download(op: urllib.request.OpenerDirector, url: str, dest: Path, size: int, sha: str) -> None:
    """断点续传下载，直到 sha256 校验通过。

    每一轮：若本地已有 N 字节，就带 `Range: bytes=N-` 续传；代理中途掐断也不丢进度。
    校验不过就删掉重来（拿到脏字节时不能抱着不放）。
    """
    attempts = 0
    while attempts < MAX_ROUNDS:
        attempts += 1
        have = dest.stat().st_size if dest.exists() else 0
        if have > size:
            print(f"  本地文件比预期大（{have}>{size}），删掉重来")
            dest.unlink(missing_ok=True)
            continue

        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with op.open(req, timeout=45) as resp, dest.open("ab" if have else "wb") as fh:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    have += len(chunk)
                    pct = have * 100 / size if size else 0
                    print(f"\r  下载 {have/1048576:.2f}/{size/1048576:.2f} MB ({pct:.0f}%)", end="")
        except Exception as exc:
            mb = have / 1048576
            print(f"\n  第 {attempts} 轮中断（{type(exc).__name__}），已存 {mb:.2f} MB，续传…")
            if attempts % 3 == 0:
                time.sleep(1.0)
            continue

        print()
        if dest.stat().st_size == size:
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if digest == sha:
                print("  sha256 校验通过 ✓")
                return
            print(f"  sha256 不匹配（期望 {sha[:16]}…，实得 {digest[:16]}…），重新下载")
            dest.unlink(missing_ok=True)
        else:
            print(f"  大小仍不足（{dest.stat().st_size}/{size}），继续续传")

    raise SystemExit(f"续传 {MAX_ROUNDS} 轮仍未完成，放弃。文件留在 {dest}，可手动接着下。")


def install(wheel: Path) -> None:
    """ruff 的 wheel 是纯二进制包，解压即得 ruff.exe，不需要 pip 安装步骤。"""
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if n.endswith("ruff.exe")]
        if not names:
            raise SystemExit(f"wheel 内没有 ruff.exe：{zf.namelist()}")
        TARGET_EXE.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(names[0]) as src, TARGET_EXE.open("wb") as dst:
            dst.write(src.read())
    print(f"已安装：{TARGET_EXE}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=PINNED_VERSION, help=f"ruff 版本，默认 {PINNED_VERSION}")
    ap.add_argument("--check", action="store_true", help="只报告状态")
    args = ap.parse_args()

    if args.check:
        print(f"ruff.exe 存在: {TARGET_EXE.exists()}")
        print(f"代理         : {PROXY}")
        return 0

    if TARGET_EXE.exists():
        print(f"已存在，跳过：{TARGET_EXE}")
        return 0

    STAGE.mkdir(parents=True, exist_ok=True)
    op = opener()

    version = args.version
    print(f"目标版本 ruff {version}（代理 {PROXY}）")

    meta = get_json(op, f"https://pypi.org/pypi/ruff/{version}/json")
    url, size, sha = pick_wheel(meta, version)
    print(f"wheel: {url.rsplit('/', 1)[-1]}  ({size/1048576:.2f} MB)")

    wheel = STAGE / url.rsplit("/", 1)[-1]
    if wheel.exists() and wheel.stat().st_size != size:
        pass  # 留给 download() 去续传
    download(op, url, wheel, size, sha)
    install(wheel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
