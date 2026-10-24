"""Application settings (ARC-01). Everything environment-specific comes from env vars so the same code
runs locally, in a Databricks App, and inside Lakeflow Jobs (ARC-04)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIM_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "local"  # local | databricks | test
    log_level: str = "INFO"

    # --- Data layer (ARC-02) -------------------------------------------------------------
    # Explicit SQLAlchemy URL wins (local dev, tests). Otherwise the Lakebase resource env vars
    # (PGHOST, PGPORT, PGDATABASE, PGUSER, PGSSLMODE) plus a generated OAuth token are used.
    database_url: str | None = None
    lakebase_instance: str | None = None
    lakebase_token_ttl_seconds: int = 50 * 60  # tokens expire hourly [D12]; refresh at 50 minutes
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Identity and RBAC (RBAC-01) ------------------------------------------------------
    role_source: str = "table"  # groups | table
    dev_user_email: str | None = None
    dev_user_roles: str = ""  # comma separated role codes, local only
    group_role_map: str = ""  # "entra-group-name=role_code;other-group=role_code" for role_source=groups

    # --- Databricks platform ----------------------------------------------------------------
    sql_warehouse_id: str | None = None
    style_master_table: str = "swim_data_whse.bluecherry.style_master"
    import_volume: str = "./local_data/imports"
    package_volume: str = "./local_data/packages"
    erp_stale_threshold_hours: int = 26

    # --- AI (AI-01) ------------------------------------------------------------------------
    ai_endpoint_copy: str = "databricks-claude-sonnet-4-5"
    ai_endpoint_classify: str = "databricks-claude-haiku-4-5"
    ai_max_tokens: int = 1024

    # --- Adapters (ARC-05, GOV-05: secrets arrive as env vars via valueFrom) ----------------
    air_api_key: str | None = None
    air_workspace_id: str | None = None
    air_base_url: str = "https://api.air.inc"
    air_boards: str = ""  # comma separated board ids to poll (IMG-01)
    shopify_store_domain: str | None = None
    shopify_read_token: str | None = None
    shopify_api_version: str = "2026-01"

    # --- Feature flags (seams for UNCONFIRMED items) ---------------------------------------
    feature_shopify_direct_write: bool = Field(default=False)  # EXP-07, off until owner approves
    feature_lakebase_cdf: bool = False  # ARC-02 history feed via CDF (Preview) vs snapshot diff job
    feature_image_embeddings: bool = False  # IMG-04
    ai_mapping_confidence_threshold: float = 0.70  # IMP-02

    @property
    def is_databricks(self) -> bool:
        return self.env == "databricks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
