"""Fill empty PIM-owned attributes from a warehouse view (seeds/attribute_seeds.yml). Fills only empty values."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402  (adjusts sys.path)


def main() -> None:
    import yaml

    from pim.config import get_settings
    from pim.db.seed import SEED_DIR
    from pim.db.session import session_scope
    from pim.services.attribute_seeds import apply_seed, read_seed_rows
    from pim.services.metadata import load_metadata

    p = argparse.ArgumentParser()
    p.add_argument("--seed", help="run one seed by code (default: all)")
    p.add_argument("--dry-run", action="store_true", help="read and count, write nothing")
    a, _ = p.parse_known_args()
    specs = (yaml.safe_load((Path(SEED_DIR) / "attribute_seeds.yml").read_text()) or {}).get("attribute_seeds", [])
    specs = [s for s in specs if not a.seed or s["code"] == a.seed]
    try:
        with session_scope() as s:
            meta = load_metadata(s, force=True)
            report = []
            for spec in specs:
                rows = read_seed_rows(spec, get_settings().sql_warehouse_id)
                report.append(apply_seed(s, meta, spec, rows))
                if a.dry_run:
                    s.rollback()
            mark_job_run(s, "succeeded", {"seeds": report, "dry_run": a.dry_run})
        print(report)
    except Exception as exc:  # noqa: BLE001
        with session_scope() as s:
            mark_job_run(s, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
