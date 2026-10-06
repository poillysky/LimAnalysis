"""将存量 DWD TEXT 列按 ETL 模型 field_type 转成真实 PG 类型，再全量重建 ADS。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.core import db as stores  # noqa: E402
from app.core.sql_ident import ident, q  # noqa: E402
from processor.agg_executor import execute_project as agg_exec  # noqa: E402
from processor.field_types import normalize_field_type, pg_type_for_field_type  # noqa: E402
from processor.models_store import get_model_by_project, list_models  # noqa: E402


def _udt(table: str, col: str) -> str:
    with stores.dwh_engine.connect() as conn:
        val = conn.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :t
                  AND column_name = :c
                """
            ),
            {"t": ident(table), "c": ident(col)},
        ).scalar()
    return str(val or "").lower()


def migrate_table(project_id: str) -> list[tuple[str, str, str]]:
    model = get_model_by_project(project_id, include_fields=True)
    if model is None:
        raise ValueError(f"no etl model for {project_id}")
    table = ident(model["target_table"])
    type_map = {"etl_at": "datetime"}
    for field in model.get("fields") or []:
        name = ident(str(field.get("target_field") or "").strip())
        if name:
            type_map[name] = normalize_field_type(field.get("field_type"))

    changed: list[tuple[str, str, str]] = []
    with stores.dwh_engine.begin() as conn:
        for col, ftype in type_map.items():
            want = pg_type_for_field_type(ftype)
            have = _udt(table, col)
            if not have:
                continue
            qc, qt = q(ident(col)), q(table)
            if want == "TIMESTAMPTZ" and have not in {"timestamptz", "timestamp"}:
                conn.execute(
                    text(
                        f"ALTER TABLE {qt} ALTER COLUMN {qc} TYPE TIMESTAMPTZ "
                        f"USING NULLIF(BTRIM({qc}::text), '')::timestamptz"
                    )
                )
                changed.append((col, have, want))
            elif want == "SMALLINT" and have not in {"int2", "int4", "int8"}:
                conn.execute(
                    text(
                        f"""
                        ALTER TABLE {qt} ALTER COLUMN {qc} TYPE SMALLINT USING (
                          CASE
                            WHEN lower(COALESCE(NULLIF(BTRIM({qc}::text), ''), ''))
                              IN ('1','true','t','y','yes','ok','pass') THEN 1
                            WHEN lower(COALESCE(NULLIF(BTRIM({qc}::text), ''), ''))
                              IN ('0','false','f','n','no','ng','fail') THEN 0
                            WHEN NULLIF(BTRIM({qc}::text), '') ~ '^-?\\d+$'
                              THEN NULLIF(BTRIM({qc}::text), '')::smallint
                            ELSE NULL
                          END
                        )
                        """
                    )
                )
                changed.append((col, have, want))
            elif want == "BIGINT" and have not in {"int8", "int4", "int2"}:
                conn.execute(
                    text(
                        f"ALTER TABLE {qt} ALTER COLUMN {qc} TYPE BIGINT "
                        f"USING NULLIF(BTRIM({qc}::text), '')::bigint"
                    )
                )
                changed.append((col, have, want))
            elif want == "NUMERIC" and have not in {
                "numeric",
                "float4",
                "float8",
                "int2",
                "int4",
                "int8",
            }:
                conn.execute(
                    text(
                        f"ALTER TABLE {qt} ALTER COLUMN {qc} TYPE NUMERIC "
                        f"USING NULLIF(BTRIM({qc}::text), '')::numeric"
                    )
                )
                changed.append((col, have, want))
    return changed


def main() -> int:
    stores.refresh_pg_engines()
    projects = sorted({m["project_id"] for m in list_models()})
    for pid in projects:
        try:
            changed = migrate_table(pid)
            print(f"{pid}: altered={changed}")
        except Exception as exc:
            print(f"{pid}: migrate skipped: {exc}")
            continue
        try:
            result = agg_exec(pid, full_refresh=True)
            print(f"{pid}: agg {result.get('message')}")
        except Exception as exc:
            print(f"{pid}: agg failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
