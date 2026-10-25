"""GET /api/health and /api/me."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pim import __version__
from pim.api.deps import CurrentUser, Session, get_current_user, get_session
from pim.config import get_settings
from pim.models._common import utcnow
from pim.services.collab import set_digest_frequency, user_setting
from pim.services.ingest import latest_successful_load

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    s = get_settings()
    last = latest_successful_load(session)
    stale = True
    if last and last.finished_at:
        stale = utcnow() - last.finished_at > timedelta(hours=s.erp_stale_threshold_hours)
    return {"status": "ok", "version": __version__, "env": s.env,
            "erp_last_load_at": last.finished_at.isoformat() if last and last.finished_at else None,
            "erp_stale": stale, "erp_stale_threshold_hours": s.erp_stale_threshold_hours,
            "features": {"shopify_direct_write": s.feature_shopify_direct_write, "lakebase_cdf": s.feature_lakebase_cdf,
                         "image_embeddings": s.feature_image_embeddings}}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return user.as_dict()


class MeSettingsBody(BaseModel):
    digest_frequency: str


def _settings_out(us) -> dict:  # noqa: ANN001
    return {"email": us.email, "digest_frequency": us.digest_frequency,
            "last_digest_at": us.last_digest_at.isoformat() if us.last_digest_at else None}


@router.get("/me/settings")
def me_settings(session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    """DM-07, DM-09: the signed-in user's digest preference (daily by default)."""
    us = user_setting(session, user.email)
    session.commit()
    return _settings_out(us)


@router.put("/me/settings")
def put_me_settings(body: MeSettingsBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        us = set_digest_frequency(session, user.email, body.digest_frequency)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return _settings_out(us)
