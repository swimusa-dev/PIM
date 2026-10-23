"""Operator CLI: `python -m pim.cli <command>`.

  init-db          create all tables (local dev and first Lakebase bootstrap; Alembic for upgrades)
  seed             load seeds/*.yml
  ingest --csv F   run the Style Master ingest from a CSV (local) or --source delta (Databricks)
  serve            run the API locally with reload
"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pim")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("seed")
    ing = sub.add_parser("ingest")
    ing.add_argument("--csv")
    ing.add_argument("--source", default="csv", choices=["csv", "delta"])
    ing.add_argument("--table")
    srv = sub.add_parser("serve")
    srv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init-db":
        import pim.models  # noqa: F401
        from pim.db.session import Base, get_engine

        Base.metadata.create_all(get_engine())
        print("tables created")
        return 0
    if args.cmd == "seed":
        from pim.db.seed import seed_all
        from pim.db.session import session_scope

        with session_scope() as s:
            print(seed_all(s))
        return 0
    if args.cmd == "ingest":
        from pim.adapters.bluecherry_source import CsvStyleMasterSource, DeltaStyleMasterSource
        from pim.db.session import session_scope
        from pim.services.ingest import run_style_master_ingest

        src = CsvStyleMasterSource(args.csv) if args.source == "csv" else DeltaStyleMasterSource(args.table)
        with session_scope() as s:
            run = run_style_master_ingest(s, src, requested_by="cli")
            print({k: getattr(run, k) for k in ("rows_read", "created", "updated", "discontinued", "placeholders_removed", "defects_found", "workflows_started")})
        return 0
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("pim.main:app", host="0.0.0.0", port=args.port, reload=True)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
