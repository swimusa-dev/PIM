"""IMP-09 / DM-07: launch workflows are for style-colors that appear after the catalog exists. The first load starts
none, and a cleanup closes the untouched tasks an earlier first load opened for the whole catalog."""

from sqlalchemy import select

from pim.models import ProductEntity, WorkflowItem
from pim.services.ingest import close_baseline_launch_items, run_style_master_ingest

BASE = {"product_type": "TOP", "division": "VITAMIN A", "sub_division": "VA CORE", "brand_name": "VIT A SWIM",
        "brand_classification": "NATIONAL BRAND", "style_description": "TEST TOP", "season": "R27",
        "style_status": "Active", "discontinued": ""}


class NoSource:
    name = "test_launch"

    def read_changes(self, since=None):
        return iter(())


def _rows(style):
    return [{**BASE, "style_number": style, "color_code": "BLK", "color_description": "BLK", "size": "S",
             "sku": f"{style}-BLK-S"}]


def _items(session, style):
    ids = [e.id for e in session.execute(select(ProductEntity).where(ProductEntity.style_number == style)).scalars()]
    return session.execute(select(WorkflowItem).where(WorkflowItem.entity_id.in_(ids))).scalars().all()


def test_the_first_load_starts_no_launch_workflows(session):
    run = run_style_master_ingest(session, NoSource(), rows=_rows("740001"))
    assert run.workflows_started == 0 and run.report["launch_workflows"] is False
    assert _items(session, "740001") == []


def test_a_style_color_that_appears_later_starts_one(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("740002"))
    run = run_style_master_ingest(session, NoSource(), rows=_rows("740002") + _rows("740003"))
    assert run.workflows_started == 1 and run.report["launch_workflows"] is True
    assert _items(session, "740002") == [] and len(_items(session, "740003")) == 1


def test_launch_workflows_can_be_forced_on_the_first_load(session):
    run = run_style_master_ingest(session, NoSource(), rows=_rows("740004"), launch_workflows=True)
    assert run.workflows_started == 1 and len(_items(session, "740004")) == 1


def test_cleanup_closes_untouched_first_load_tasks_only(session):
    run_style_master_ingest(session, NoSource(), rows=_rows("740005") + _rows("740006"), launch_workflows=True)
    worked = _items(session, "740006")[0]
    worked.history = [*worked.history, {"event": "completed", "by": "someone@swimusa.com"}]
    run_style_master_ingest(session, NoSource(), rows=_rows("740007"))  # a later load: its task must stay
    session.flush()
    assert close_baseline_launch_items(session) == 1
    assert [i.state for i in _items(session, "740005")] == ["cancelled"]
    assert _items(session, "740005")[0].history[-1]["event"] == "cancelled"
    assert [i.state for i in _items(session, "740006")] == ["open"]
    assert [i.state for i in _items(session, "740007")] == ["open"]
    assert close_baseline_launch_items(session) == 0  # safe to repeat
