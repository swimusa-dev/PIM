from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from pim.auth.identity import CurrentUser, get_current_user
from pim.db.session import get_session
from pim.services.metadata import Metadata, load_metadata


def get_meta(session: Session = Depends(get_session)) -> Metadata:
    return load_metadata(session)


__all__ = ["CurrentUser", "Metadata", "Session", "get_current_user", "get_meta", "get_session"]
