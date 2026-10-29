"""In-process metadata cache (P5). Every screen, import, rule, and export reads attribute definitions from here.
Invalidate after admin writes (`invalidate()`); otherwise entries refresh every 30 seconds."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pim.models import (
    AttributeDefinition,
    AttributeGroup,
    BrandScope,
    Channel,
    ChannelRequirementBinding,
    ChannelRequirementSet,
    Family,
    OptionList,
    PlaceholderToken,
    ReferenceEntityType,
    ShotType,
    ValueMapping,
)
from pim.normalization import Normalizer

LEVEL_ORDER = {"style": 0, "style_color": 1, "sku": 2}


@dataclass
class Metadata:
    attributes: dict[str, AttributeDefinition]
    groups: dict[str, AttributeGroup]
    option_lists: dict[str, OptionList]
    families: dict[str, Family]
    channels: dict[str, Channel]
    requirement_sets: dict[str, ChannelRequirementSet]
    bindings: list[ChannelRequirementBinding]
    reference_types: dict[str, ReferenceEntityType]
    shot_types: dict[str, ShotType]
    brand_scopes: list[BrandScope]
    normalizer: Normalizer
    value_mappings: dict[tuple[str, str], dict[str, str | None]]  # (source, list) -> normalized raw -> option
    loaded_at: float = field(default_factory=time.monotonic)

    # ---- helpers ---------------------------------------------------------------------------------
    def attributes_for_level(self, level: str) -> list[AttributeDefinition]:
        return sorted(
            (a for a in self.attributes.values() if a.level == level and a.status != "deprecated"),
            key=lambda a: (self.groups[a.group_code].sort_order if a.group_code in self.groups else 999, a.sort_order, a.code),
        )

    def groups_for_family(self, family_code: str | None) -> list[AttributeGroup]:
        fam = self.families.get(family_code or "") or self.families.get("unassigned")
        if fam is None:
            return sorted(self.groups.values(), key=lambda g: g.sort_order)
        codes = [fg.group_code for fg in sorted(fam.groups, key=lambda x: x.sort_order)]
        return [self.groups[c] for c in codes if c in self.groups]

    def attributes_for_family(self, family_code: str | None, level: str | None = None) -> list[AttributeDefinition]:
        out: list[AttributeDefinition] = []
        for g in self.groups_for_family(family_code):
            for a in sorted(g.attributes, key=lambda a: (a.sort_order, a.code)):
                if a.status == "deprecated":
                    continue
                if level and a.level != level:
                    continue
                out.append(a)
        return out

    def requirement_set_for(self, channel_code: str, family_code: str | None) -> ChannelRequirementSet | None:
        best = None
        for b in self.bindings:
            if b.channel_code != channel_code:
                continue
            if b.family_code == (family_code or ""):
                best = b
                break
            if b.family_code == "*" and best is None:
                best = b
        return self.requirement_sets.get(best.set_code) if best else None

    def option_codes(self, list_code: str | None) -> set[str]:
        lst = self.option_lists.get(list_code or "")
        return {v.code for v in lst.values} if lst else set()

    def option_label(self, list_code: str | None, code: str | None) -> str | None:
        lst = self.option_lists.get(list_code or "")
        if not lst or code is None:
            return None
        for v in lst.values:
            if v.code == code:
                return v.label
        return None

    def size_scale_entry(self, size: str | None):
        """DM-14: find the scale entry for a Style Master size value."""
        if not size:
            return None
        key = SIZE_ALIASES.get(size.strip().upper(), size.strip().upper())
        for lst in self.option_lists.values():
            if lst.kind != "size_scale":
                continue
            for v in lst.values:
                if v.code.upper() == key:
                    return lst, v
        return None


# Style Master spellings of a size that is the same size under another code (a scale value of its own would
# duplicate the channel mappings): the abbreviated alphas, the dashed and abbreviated ranges, and the two "no size"
# markers.
SIZE_ALIASES = {"LG": "L", "SM": "S", "MD": "M", "MED": "M", "LRG": "L", "NOSIZ": "OS", "NS": "OS",
                "S-M": "S/M", "SM/MD": "S/M", "M-L": "M/L", "L-XL": "L/XL", "LG/XL": "L/XL"}
# A pack, not a size: the SKU is a prepack and has no size to check against a scale. PP, and the 10L to 18L range packs
# (each holds 10L, 12L, 14L, 16L and 18L).
PREPACK_SIZES = {"PP", "10L", "12L", "14L", "16L", "18L"}
# Not a size and not a pack either (PCS is a piece count, typically an accessory): nothing to check against a scale.
NON_SIZE_VALUES = {"PCS"}


_cache: Metadata | None = None
_TTL = 30.0


def invalidate() -> None:
    global _cache
    _cache = None


def load_metadata(session: Session, force: bool = False) -> Metadata:
    global _cache
    if _cache is not None and not force and time.monotonic() - _cache.loaded_at < _TTL:
        return _cache
    attrs = session.execute(select(AttributeDefinition)).scalars().all()
    groups = session.execute(select(AttributeGroup).options(selectinload(AttributeGroup.attributes))).scalars().all()
    lists = session.execute(select(OptionList).options(selectinload(OptionList.values))).scalars().all()
    fams = session.execute(select(Family).options(selectinload(Family.groups))).scalars().all()
    chans = session.execute(select(Channel)).scalars().all()
    sets = session.execute(
        select(ChannelRequirementSet).options(selectinload(ChannelRequirementSet.requirements))
    ).scalars().all()
    bindings = session.execute(select(ChannelRequirementBinding)).scalars().all()
    rtypes = session.execute(select(ReferenceEntityType)).scalars().all()
    shots = session.execute(select(ShotType)).scalars().all()
    scopes = session.execute(select(BrandScope)).scalars().all()
    tokens = session.execute(select(PlaceholderToken).where(PlaceholderToken.enabled.is_(True))).scalars().all()
    vms = session.execute(select(ValueMapping)).scalars().all()
    mapping: dict[tuple[str, str], dict[str, str | None]] = {}
    for vm in vms:
        mapping.setdefault((vm.source_code, vm.list_code), {})[vm.raw_normalized] = vm.option_code
    for obj in attrs + groups + lists + fams + chans + sets + bindings + rtypes + shots + scopes:
        session.expunge(obj)
    _cache = Metadata(
        attributes={a.code: a for a in attrs},
        groups={g.code: g for g in groups},
        option_lists={o.code: o for o in lists},
        families={f.code: f for f in fams},
        channels={c.code: c for c in chans},
        requirement_sets={s.code: s for s in sets},
        bindings=list(bindings),
        reference_types={r.code: r for r in rtypes},
        shot_types={s.code: s for s in shots},
        brand_scopes=list(scopes),
        normalizer=Normalizer({t.token: t.means_not_applicable for t in tokens} or None),
        value_mappings=mapping,
    )
    return _cache
