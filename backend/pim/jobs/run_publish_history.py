"""ARC-02 / GOV-02: publish a read-optimized golden record and the value history to Delta.

Seam: if PIM_FEATURE_LAKEBASE_CDF is on and the Lakebase Change Data Feed passes review, this job becomes a
no-op for history and only refreshes the gold tables. Until then it writes history by reading value_history
rows newer than the last published watermark.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from sqlalchemy import select

    from pim.config import get_settings
    from pim.db.session import session_scope
    from pim.models import ProductEntity, ProductValue, ValueHistory

    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default="swim_data_whse")
    p.add_argument("--schema", default="pim")
    a, _ = p.parse_known_args()
    s = get_settings()
    import time

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import Disposition, StatementState

    w = WorkspaceClient()

    def sql(stmt: str) -> None:
        resp = w.statement_execution.execute_statement(statement=stmt, warehouse_id=s.sql_warehouse_id, wait_timeout="50s",
                                                       disposition=Disposition.INLINE)
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(resp.statement_id)
        if resp.status is None or resp.status.state != StatementState.SUCCEEDED:
            err = resp.status.error if resp.status else None
            raise RuntimeError(f"SQL statement failed ({resp.status.state if resp.status else 'no status'}): {err}; {stmt[:160]}")

    with session_scope() as session:
        sql(f"CREATE SCHEMA IF NOT EXISTS {a.catalog}.{a.schema}")
        sql(f"""CREATE TABLE IF NOT EXISTS {a.catalog}.{a.schema}.gold_product_value (
                entity_id STRING, entity_level STRING, style_number STRING, color_code STRING, size STRING, sku STRING,
                attribute_code STRING, channel_code STRING, value STRING, source_type STRING, approval_state STRING,
                ai_generated BOOLEAN, set_by STRING, set_at TIMESTAMP, version INT, published_at TIMESTAMP) USING DELTA""")
        sql(f"""CREATE TABLE IF NOT EXISTS {a.catalog}.{a.schema}.value_history (
                id STRING, entity_id STRING, attribute_code STRING, channel_code STRING, old_value STRING, new_value STRING,
                source_type STRING, set_by STRING, set_at TIMESTAMP, change_set_id STRING, version INT) USING DELTA""")
        ents = {e.id: e for e in session.execute(select(ProductEntity)).scalars()}
        rows = []
        for pv in session.execute(select(ProductValue)).scalars():
            e = ents.get(pv.entity_id)
            val = pv.value_text or (str(pv.value_number) if pv.value_number is not None else None) or \
                (str(pv.value_bool) if pv.value_bool is not None else None) or (pv.value_date.isoformat() if pv.value_date else None) or \
                (json.dumps(pv.value_json) if pv.value_json is not None else None) or pv.value_ref
            rows.append((pv.entity_id, pv.entity_level, e.style_number if e else None, e.color_code if e else None, e.size if e else None,
                         e.sku if e else None, pv.attribute_code, pv.channel_code, val, pv.source_type, pv.approval_state,
                         pv.ai_generated, pv.set_by, pv.set_at.isoformat(), pv.version))
        if not s.feature_lakebase_cdf:
            hist = session.execute(select(ValueHistory)).scalars().all()
        else:
            hist = []
        # Batched inserts through SQL; for very large catalogs replace with a Volume staging file + COPY INTO.
        for i in range(0, len(rows), 500):
            values = ",".join("(" + ",".join(_lit(v) for v in r) + ",current_timestamp())" for r in rows[i:i + 500])
            sql(f"INSERT OVERWRITE {a.catalog}.{a.schema}.gold_product_value VALUES {values}" if i == 0 else
                f"INSERT INTO {a.catalog}.{a.schema}.gold_product_value VALUES {values}")
        for i in range(0, len(hist), 500):
            values = ",".join("(" + ",".join(_lit(v) for v in (h.id, h.entity_id, h.attribute_code, h.channel_code, json.dumps(h.old_value),
                                                                   json.dumps(h.new_value), h.source_type, h.set_by, h.set_at.isoformat(),
                                                                   h.change_set_id, h.version)) + ")" for h in hist[i:i + 500])
            sql(f"MERGE INTO {a.catalog}.{a.schema}.value_history t USING (SELECT * FROM VALUES {values} AS v(id, entity_id, attribute_code, channel_code, old_value, new_value, source_type, set_by, set_at, change_set_id, version)) src ON t.id = src.id WHEN NOT MATCHED THEN INSERT *")
        # GOV-02: the Delta copy now holds every history row, so rows past the hot window leave Lakebase
        from pim.services.history import prune_history

        pruned = prune_history(session)  # CDF mode streams history to Delta; otherwise the MERGE above just completed
        mark_job_run(session, "succeeded", {"gold_rows": len(rows), "history_rows": len(hist), "history_pruned": pruned})


def _lit(v) -> str:  # noqa: ANN001
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


if __name__ == "__main__":
    main()
