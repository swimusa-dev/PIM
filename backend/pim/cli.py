"""Operator CLI: `python -m pim.cli <command>`.

  init-db          create all tables (local dev and first Lakebase bootstrap; Alembic for upgrades)
  seed             load seeds/*.yml
  ingest --csv F   run the Style Master ingest from a CSV (local) or --source delta (Databricks)
  serve            run the API locally with reload
  setup-file       fill a Product Information Setup File from the PIM (--fill F) or build one (--styles "6000150,6131286-KLP")
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
    sf = sub.add_parser("setup-file")
    sf_src = sf.add_mutually_exclusive_group(required=True)
    sf_src.add_argument("--fill", help="an existing setup file (.xlsx) to fill in with PIM values")
    sf_src.add_argument("--styles", help="style numbers, optionally STYLE-COLOR, separated by commas or new lines")
    sf.add_argument("--out", required=True, help="where to write the .xlsx")
    sf.add_argument("--keep-file-values", action="store_true", help="only fill empty cells; never replace a value in the file")
    sf.add_argument("--as-user", default="cli@swimusa.com", help="email whose roles and brand scopes apply (cost columns need view_cost)")
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
    if args.cmd == "setup-file":
        return _setup_file(args)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("pim.main:app", host="0.0.0.0", port=args.port, reload=True)
        return 0
    return 1


def _setup_file(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from sqlalchemy import select

    from pim.auth.identity import build_user
    from pim.db.session import session_scope
    from pim.export.setup_file import (
        build_setup_workbook,
        fill_setup_workbook,
        parse_style_keys,
        style_colors_for,
    )
    from pim.models import UserRole
    from pim.services.metadata import load_metadata

    with session_scope() as s:
        grants = s.execute(select(UserRole).where(UserRole.email == args.as_user)).scalars().all()
        roles = [g.role_code for g in grants] or ["pim_admin"]
        scopes = sorted({sc for g in grants for sc in (g.brand_scopes or [])})
        user = build_user(args.as_user, None, roles, scopes, s)
        meta = load_metadata(s)
        if args.fill:
            src = Path(args.fill)
            result = fill_setup_workbook(s, meta, user, src.read_bytes(), src.name, keep_file_values=args.keep_file_values)
            extra: dict = {}
        else:
            ents, missing = style_colors_for(s, user, parse_style_keys(args.styles))
            ents.sort(key=lambda e: (e.style_number, e.color_code or ""))
            result = build_setup_workbook(s, meta, user, ents)
            extra = {"styles_not_found": missing}
        s.rollback()  # read-only command
    Path(args.out).write_bytes(result.content)
    print(json.dumps({**result.summary, **extra, "written_to": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
