"""Saved views (DM-02)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select

from pim.api.deps import CurrentUser, Session, get_current_user, get_session
from pim.api.schemas import ViewBody, ViewPatch
from pim.api.serializers import view_out
from pim.models import SavedView

router = APIRouter(prefix="/api/views", tags=["views"])


def _visible(user: CurrentUser):
    conds = [SavedView.owner_email == user.email, SavedView.shared_with == "everyone"]
    conds += [SavedView.shared_with == f"role:{r}" for r in user.roles]
    return or_(*conds)


@router.get("")
def list_views(level: str | None = None, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    q = select(SavedView).where(_visible(user))
    if level:
        q = q.where(SavedView.level == level)
    return [view_out(v) for v in session.execute(q.order_by(SavedView.name)).scalars()]


@router.post("")
def create_view(body: ViewBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    v = SavedView(owner_email=user.email, **body.model_dump())
    if v.is_default:
        for other in session.execute(select(SavedView).where(SavedView.owner_email == user.email, SavedView.is_default.is_(True))).scalars():
            other.is_default = False
    session.add(v)
    session.commit()
    return view_out(v)


@router.put("/{view_id}")
def update_view(view_id: str, body: ViewPatch, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    v = session.get(SavedView, view_id)
    if v is None:
        raise HTTPException(404, "View not found")
    if v.owner_email != user.email:
        raise HTTPException(403, "Only the creator edits a shared view; duplicate it instead")
    for k, val in body.model_dump(exclude_none=True).items():
        setattr(v, k, val)
    if v.is_default:
        for other in session.execute(select(SavedView).where(SavedView.owner_email == user.email, SavedView.is_default.is_(True), SavedView.id != v.id)).scalars():
            other.is_default = False
    session.commit()
    return view_out(v)


@router.delete("/{view_id}")
def delete_view(view_id: str, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    v = session.get(SavedView, view_id)
    if v is None:
        raise HTTPException(404, "View not found")
    if v.owner_email != user.email and not user.can("admin_metadata"):
        raise HTTPException(403, "Only the creator deletes a view")
    session.delete(v)
    session.commit()
    return {"deleted": view_id}
