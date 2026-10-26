"""IMG-07 rendition job: refresh Air CDN renditions for every channel with an image profile and resize the ones
Air could not serve (source=pending) with Pillow into the publish volume."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Databricks runs this file directly, so put backend/ on the path before the first `pim` import.
sys.path.insert(0, str(Path(globals().get("__file__") or sys.argv[0]).resolve().parents[2]))

from pim.jobs._common import mark_job_run  # noqa: E402

log = logging.getLogger(__name__)


def main() -> None:
    import httpx
    from sqlalchemy import select

    from pim.adapters.base import NotConfigured
    from pim.db.session import session_scope
    from pim.export.publishing import storage
    from pim.models import Channel
    from pim.services import images_phase3 as svc

    report: dict = {}
    with session_scope() as s:
        air = None
        try:
            from pim.adapters.air_dam import AirClient

            air = AirClient()
        except NotConfigured:
            air = None
        for ch in s.execute(select(Channel)).scalars():
            if ch.image_profile:
                report[ch.code] = svc.refresh_renditions(s, ch, None, air)
                s.commit()

        def fetch(asset) -> bytes:  # noqa: ANN001
            if not asset.thumbnail_url:
                raise RuntimeError("asset has no downloadable URL in the snapshot")
            return httpx.get(asset.thumbnail_url, timeout=60.0, follow_redirects=True).content

        report["pillow_rendered"] = svc.render_pending_with_pillow(s, fetch, storage())
        mark_job_run(s, "succeeded", report)


if __name__ == "__main__":
    main()
