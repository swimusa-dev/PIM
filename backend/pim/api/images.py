"""Phase 3 image API: ordering (IMG-05), AI-generated flag and write-back (IMG-06), tier 3 candidates (IMG-03),
renditions (IMG-07)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from pim.adapters.base import NotConfigured
from pim.api.deps import CurrentUser, Metadata, Session, get_current_user, get_meta, get_session
from pim.api.schemas import AssetPatchBody, ImageOrderBody, RenditionRefreshBody
from pim.models import Asset, AssetLink, Channel, ImageRendition, ProductEntity
from pim.services import images_phase3 as svc
from pim.services.readiness import refresh_snapshots

router = APIRouter(prefix="/api", tags=["images"])


def _can_assign(user: CurrentUser) -> None:
    if not user.can_edit_group("channel_shopify") and not user.can("admin_metadata"):
        raise HTTPException(403, "Image assignment requires edit rights on the Shopify channel group")


@router.put("/products/{entity_id}/images/order")
def order_images(entity_id: str, body: ImageOrderBody, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                 user: CurrentUser = Depends(get_current_user)) -> dict:
    ent = session.get(ProductEntity, entity_id)
    if ent is None or not user.in_brand_scope(ent.brand_scopes or []):
        raise HTTPException(404, "Product not found")
    _can_assign(user)
    target = ent if ent.level == "style_color" else (session.get(ProductEntity, ent.parent_id) if ent.parent_id else None)
    if target is None:
        raise HTTPException(400, "Images belong to style-colors")
    try:
        links = svc.reorder_links(session, target.id, body.link_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {"links": [svc.link_out_phase3(lk, meta, target.family_code) for lk in links]}


@router.put("/images/assets/{asset_id}")
def patch_asset(asset_id: str, body: AssetPatchBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    _can_assign(user)
    a = session.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    a.ai_generated_image = body.ai_generated_image
    session.commit()
    return {"asset_id": a.id, "ai_generated_image": a.ai_generated_image}


@router.post("/images/assets/{asset_id}/ai-candidates")
def asset_ai_candidates(asset_id: str, session: Session = Depends(get_session), meta: Metadata = Depends(get_meta),
                        user: CurrentUser = Depends(get_current_user)) -> dict:
    _can_assign(user)
    a = session.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    air = None
    try:
        from pim.adapters.air_dam import AirClient

        air = AirClient()
    except NotConfigured:
        air = None
    from pim.ai.service import AIService

    try:
        links = svc.ai_candidates(session, meta, a, air_client=air, ai_service=AIService(), user_email=user.email)
    except svc.FeatureOff as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    ents = {e.id: e for e in session.execute(select(ProductEntity).where(ProductEntity.id.in_({lk.entity_id for lk in links}))).scalars()} if links else {}
    return {"candidates": [{**svc.link_out_phase3(lk, meta, ents[lk.entity_id].family_code if lk.entity_id in ents else None),
                            "product_label": ents[lk.entity_id].label if lk.entity_id in ents else lk.entity_id} for lk in links]}


@router.get("/images/assets/{asset_id}/renditions")
def asset_renditions(asset_id: str, channel: str | None = None, session: Session = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    a = session.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    if channel:
        ch = session.get(Channel, channel)
        if ch is None:
            raise HTTPException(404, "Unknown channel")
        svc.ensure_rendition(session, ch, a)
        session.commit()
    q = select(ImageRendition).where(ImageRendition.asset_id == asset_id)
    if channel:
        q = q.where(ImageRendition.channel_code == channel)
    return [svc.rendition_out(r) for r in session.execute(q.order_by(ImageRendition.created_at.desc())).scalars()]


@router.post("/images/renditions/refresh")
def refresh_renditions(body: RenditionRefreshBody, session: Session = Depends(get_session), user: CurrentUser = Depends(get_current_user)) -> dict:
    if not (user.channel_right(body.channel_code, "run") or user.can("admin_metadata")):
        raise HTTPException(403, "No right to run exports for this channel (RBAC-03)")
    ch = session.get(Channel, body.channel_code)
    if ch is None:
        raise HTTPException(404, "Unknown channel")
    if not ch.image_profile:
        raise HTTPException(400, "The channel has no image profile yet (IMG-07)")
    result = svc.refresh_renditions(session, ch, body.entity_ids)
    session.commit()
    return result


__all__ = ["router", "AssetLink", "refresh_snapshots"]
