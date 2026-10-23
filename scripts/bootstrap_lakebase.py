"""One-time Lakebase bootstrap run from a laptop or a job: create tables (Alembic) and load seed metadata.

Usage (laptop, Databricks CLI profile logged in):
    export PIM_LAKEBASE_INSTANCE=pim-lakebase PGHOST=<instance host> PGUSER=<your user or SP id> PGDATABASE=pim PGSSLMODE=require
    python scripts/bootstrap_lakebase.py
The OAuth token is generated through the Databricks SDK, so no password is needed (ARC-02).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pim.db.seed import seed_all  # noqa: E402
from pim.db.session import session_scope  # noqa: E402

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    with session_scope() as s:
        print("seeded:", seed_all(s))
