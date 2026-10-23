"""EXP-13: build a package in the background (used when the selection is large)."""

from __future__ import annotations

import argparse

from pim.jobs._common import mark_job_run  # noqa: E402


def main() -> None:
    from pim.adapters.shopify_admin import ShopifyAdminClient, parse_product_csv
    from pim.config import get_settings
    from pim.db.session import session_scope
    from pim.export.shopify_package import build_package
    from pim.models import UpdatePackage
    from pim.models._common import utcnow
    from pim.services.metadata import load_metadata
    from pim.services.storage import Storage

    p = argparse.ArgumentParser()
    p.add_argument("--package-id", required=True)
    a, _ = p.parse_known_args()
    storage = Storage(get_settings().package_volume)
    with session_scope() as session:
        pkg = session.get(UpdatePackage, a.package_id)
        if pkg is None:
            raise SystemExit(f"package {a.package_id} not found")
        snap = parse_product_csv(storage.read(pkg.snapshot_path)) if pkg.snapshot_mode == "csv_upload" else ShopifyAdminClient().snapshot_via_bulk()
        pkg.snapshot_at = utcnow()
        build_package(session, load_metadata(session, force=True), None, pkg, snap, storage)
        mark_job_run(session, "succeeded", {"package_id": pkg.id, "changes": pkg.change_count})


if __name__ == "__main__":
    main()
