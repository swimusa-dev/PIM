"""The app definition must deploy: Databricks Apps allow at most 20 resources, and the resources bound to the app and the
env vars app.yaml injects from them must agree. Neither can be seen until a deploy fails, so check them here."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAX_APP_RESOURCES = 20


def _app_resources() -> list[dict]:
    return yaml.safe_load((ROOT / "resources" / "app.yml").read_text())["resources"]["apps"]["pim_app"]["resources"]


def _injected() -> set[str]:
    return set(re.findall(r"valueFrom:\s*([\w-]+)", (ROOT / "app.yaml").read_text()))


def test_the_app_has_no_more_resources_than_databricks_allows():
    names = [r["name"] for r in _app_resources()]
    assert len(names) == len(set(names)), "duplicate resource name"
    assert len(names) <= MAX_APP_RESOURCES, f"{len(names)} app resources; Databricks Apps allow {MAX_APP_RESOURCES}"


def test_every_env_var_comes_from_a_resource_and_every_resource_is_used():
    names = {r["name"] for r in _app_resources()}
    assert _injected() <= names, f"app.yaml reads resources the app does not have: {sorted(_injected() - names)}"
    assert names <= _injected(), f"resources the app never reads (they use up the limit): {sorted(names - _injected())}"


def test_every_job_the_app_can_start_is_a_bound_resource():
    from pim.services.jobs import JOB_ENV

    env = set(re.findall(r"-\s*name:\s*(DATABRICKS_JOB_ID_\w+)", (ROOT / "app.yaml").read_text()))
    assert set(JOB_ENV.values()) <= env, f"jobs the app starts but app.yaml does not inject: {sorted(set(JOB_ENV.values()) - env)}"
