"""AI-05 document inputs: production path is Databricks `ai_parse_document` on the SQL warehouse (D28); the local
fallback in tasks.document_text uses pypdf when installed."""

from __future__ import annotations

import base64

from pim.adapters.base import NotConfigured
from pim.config import get_settings


def parse_with_databricks(raw: bytes, name: str) -> str:
    s = get_settings()
    warehouse = getattr(s, "sql_warehouse_id", None)
    if not warehouse:
        raise NotConfigured("PIM_SQL_WAREHOUSE_ID is not set; ai_parse_document needs a SQL warehouse (D28)")
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    w = WorkspaceClient()
    b64 = base64.b64encode(raw).decode()
    stmt = w.statement_execution.execute_statement(
        warehouse_id=warehouse, wait_timeout="50s",
        statement="SELECT ai_parse_document(unbase64(:doc)):document.pages[*].content AS pages",
        parameters=[StatementParameterListItem(name="doc", value=b64)])
    if stmt.status is None or stmt.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"ai_parse_document failed for {name}: {stmt.status.error.message if stmt.status and stmt.status.error else stmt.status}")
    rows = (stmt.result.data_array if stmt.result else None) or []
    return "\n".join(str(r[0]) for r in rows if r and r[0])
