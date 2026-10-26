"""The Image Relay export view is 3 million rows by 166 columns; the Delta source must narrow and slice its reads."""

import re
from types import SimpleNamespace

import databricks.sdk
from databricks.sdk.service.sql import StatementState

from pim.adapters.bluecherry_source import DeltaStyleMasterSource
from pim.services.ingest import run_style_master_ingest

DESCRIBE = [["Style #", "string", None], ["Color Cd", "string", None], ["Style Master Size", "string", None],
            ["Division Name", "string", None], ["Style Content Desc", "string", None], ["Noise Col", "string", None],
            ["", "", ""], ["# Partitioning", "", ""], ["Part 0", "", ""]]
SLICE_ROWS = {3: [["100", "BLK", "S", "Swim", "Nylon"]], 7: [["200", "RED", "M", "Swim", "Poly"]]}


class FakeWarehouse:
    def __init__(self):
        self.statements = []
        self.statement_execution = self

    def execute_statement(self, statement, **kwargs):
        self.statements.append(statement)
        if statement.startswith("DESCRIBE"):
            cols, data = ["col_name", "data_type", "comment"], DESCRIBE
        else:
            k = int(re.search(r"= (\d+)$", statement).group(1))
            cols = [c.strip("` ") for c in re.search(r"SELECT DISTINCT (.*) FROM", statement).group(1).split(", ")]
            data = SLICE_ROWS.get(k, [])
        return SimpleNamespace(
            status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None), statement_id="s",
            manifest=SimpleNamespace(schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in cols])),
            result=SimpleNamespace(data_array=data, next_chunk_index=None))


def _read(monkeypatch, wanted):
    fake = FakeWarehouse()
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", lambda: fake)
    src = DeltaStyleMasterSource("cat.sch.vw", "wh1")
    src.wanted_columns = wanted
    return fake, list(src.read_changes())


def test_reads_only_needed_columns_deduplicated_in_slices(monkeypatch):
    fake, rows = _read(monkeypatch, {"style_content_desc"})
    selects = fake.statements[1:]
    assert fake.statements[0] == "DESCRIBE TABLE cat.sch.vw" and len(selects) == DeltaStyleMasterSource.SLICES
    assert all(s.startswith("SELECT DISTINCT ") and "Noise Col" not in s and "`Style Content Desc`" in s for s in selects)
    assert sorted(re.search(r"= (\d+)$", s).group(1) for s in selects) == sorted(str(k) for k in range(16))
    assert all("pmod(xxhash64(`Style #`), 16)" in s for s in selects)
    assert [(r["style_number"], r["color_code"], r["size"], r["division"], r["style_content_desc"]) for r in rows] == [
        ("100", "BLK", "S", "Swim", "Nylon"), ("200", "RED", "M", "Swim", "Poly")]


def test_without_a_column_list_every_column_is_read(monkeypatch):
    fake, _ = _read(monkeypatch, None)
    assert "`Noise Col`" in fake.statements[1]


def test_ingest_tells_the_source_which_columns_it_reads(session):
    class Src:
        name = "test"
        wanted_columns = None

        def read_changes(self, since=None):
            return iter(())

    src = Src()
    run_style_master_ingest(session, src)
    assert {"material_claim", "style_content_desc", "msrp"} <= src.wanted_columns
