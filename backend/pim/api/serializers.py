from __future__ import annotations

from pim.models import AttributeDefinition, AttributeGroup, Channel, Family, OptionList, SavedView
from pim.services.metadata import Metadata


def attribute_out(a: AttributeDefinition) -> dict:
    return {
        "code": a.code, "label": a.label, "data_type": a.data_type, "level": a.level, "group_code": a.group_code,
        "sort_order": a.sort_order, "option_list_code": a.option_list_code, "reference_type_code": a.reference_type_code,
        "unit": a.unit, "validation": a.validation or {}, "channel_scopable": a.channel_scopable,
        "allows_not_applicable": a.allows_not_applicable, "default_value": a.default_value,
        "default_families": a.default_families or [], "owner_role": a.owner_role, "owner_person": a.owner_person,
        "status": a.status, "source_of_truth": a.source_of_truth, "help_text": a.help_text,
        "example_value": a.example_value, "erp_column": a.erp_column, "not_required_means_na": a.not_required_means_na,
        "cost_restricted": a.cost_restricted,
    }


def group_out(g: AttributeGroup) -> dict:
    return {"code": g.code, "label": g.label, "owning_role": g.owning_role, "sort_order": g.sort_order,
            "read_only": g.read_only, "survivorship": g.survivorship, "exclude_from_quality": g.exclude_from_quality,
            "channel_code": g.channel_code}


def option_list_out(o: OptionList) -> dict:
    return {"code": o.code, "label": o.label, "kind": o.kind, "size_group": o.size_group,
            "values": [{"code": v.code, "label": v.label, "sort_order": v.sort_order,
                        "channel_mappings": v.channel_mappings or {}} for v in o.values]}


def family_out(f: Family) -> dict:
    return {"code": f.code, "label": f.label, "erp_match": f.erp_match or {},
            "group_codes": [g.group_code for g in sorted(f.groups, key=lambda x: x.sort_order)]}


def channel_out(c: Channel, meta: Metadata) -> dict:
    binding = next((b for b in meta.bindings if b.channel_code == c.code and b.family_code == "*"), None)
    return {"code": c.code, "label": c.label, "adapter": c.adapter, "kind": c.kind, "enabled": c.enabled,
            "requirement_set_code": binding.set_code if binding else None, "protected_fields": c.protected_fields or [],
            "attribute_mapping": c.attribute_mapping or {}, "eligibility": c.eligibility or {}, "config": c.config or {},
            "version": c.version}


def view_out(v: SavedView) -> dict:
    return {"id": v.id, "name": v.name, "level": v.level, "owner_email": v.owner_email, "shared_with": v.shared_with,
            "is_default": v.is_default, "definition": v.definition or {}, "updated_at": v.updated_at.isoformat()}
