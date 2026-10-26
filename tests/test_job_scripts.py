"""Lakeflow Jobs run the script file directly, so `pim` is not importable until the script puts backend/ on sys.path."""

import ast
from pathlib import Path

import pytest

JOBS = sorted((Path(__file__).resolve().parents[1] / "backend" / "pim" / "jobs").glob("run_*.py"))


@pytest.mark.parametrize("path", JOBS, ids=lambda p: p.name)
def test_job_script_sets_sys_path_before_importing_pim(path):
    tree = ast.parse(path.read_text())
    path_line = next(
        (n.lineno for n in tree.body
         if isinstance(n, ast.Expr) and "sys.path.insert" in ast.unparse(n)), None)
    first_pim_import = next(
        (n.lineno for n in tree.body
         if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "pim"), None)
    assert path_line is not None, f"{path.name} never adjusts sys.path"
    assert first_pim_import is None or path_line < first_pim_import
