"""按参考 CSV 表头清理 lim_raw 宽表中的历史脏列。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.core.db import raw_engine, refresh_pg_engines
from app.core.sql_ident import unique_idents
from collector.raw_loader import (
    decode_csv,
    drop_stale_columns,
    ensure_conflict_target,
    parse_csv,
    relax_legacy_primary_key,
    unique_column,
)

SAMPLES = {
    "eagle_rcvr_raw": REPO
    / "refence"
    / "legacy-src"
    / "SFCEagleRcvr_all_20261002_104723.csv",
    "whale_spkr_raw": REPO
    / "refence"
    / "legacy-src"
    / "SFCWhaleSpkr_all_20261002_104619.csv",
}


def main() -> None:
    refresh_pg_engines()
    for table, path in SAMPLES.items():
        text = decode_csv(path.read_bytes())
        frame = parse_csv(text)
        pk_src = unique_column(frame)
        cols = unique_idents([str(c) for c in frame.columns])
        rename = dict(zip((str(s) for s in frame.columns), cols, strict=True))
        pk = rename[pk_src]
        relax_legacy_primary_key(raw_engine, table, pk)
        dropped = drop_stale_columns(raw_engine, table, cols)
        ensure_conflict_target(raw_engine, table, pk)
        print(f"{table}: keep={len(cols)} dropped={len(dropped)} {dropped[:20]}")


if __name__ == "__main__":
    main()
