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
    publish_volume: str | None = None  # EXP-05 payloads and renditions; defaults to package_volume
    erp_stale_threshold_hours: int = 26
    mention_domain: str = "swimusa.com"  # DM-09: "@first.last" resolves to this domain

    # --- AI (AI-01) ------------------------------------------------------------------------
    ai_endpoint_copy: str = "databricks-claude-sonnet-4-5"
    ai_endpoint_classify: str = "databricks-claude-haiku-4-5"
    ai_max_tokens: int = 1024
    ai_eval_threshold: float = 0.05  # AI-07: block a template when the composite drops by more than this
    ai_eval_min_cases: int = 5
    mlflow_experiment: str | None = None  # AI-07: log evaluation runs when set, for example /Shared/pim-ai-eval
    ai_classify_confidence_threshold: float = 0.75  # AI-05 classify: below this the result is shown, not drafted

    # --- Adapters (ARC-05, GOV-05: secrets arrive as env vars via valueFrom) ----------------
    air_api_key: str | None = None
    air_workspace_id: str | None = None
    air_base_url: str = "https://api.air.inc"
    air_boards: str = ""  # comma separated board ids to poll (IMG-01)
    shopify_store_domain: str | None = None
    shopify_read_token: str | None = None
    shopify_api_version: str = "2026-01"
    shopify_sandbox_domain: str | None = None  # D-03: development store for the write-path sandbox run
    shopify_sandbox_token: str | None = None
    walmart_client_id: str | None = None  # EXP-08 (secrets walmart-client-id, walmart-client-secret)
    walmart_client_secret: str | None = None
    walmart_base_url: str = "https://marketplace.walmartapis.com"
    smtp_host: str | None = None  # EXP-09 email delivery
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    # --- Feature flags (seams for UNCONFIRMED items) ---------------------------------------
    feature_shopify_direct_write: bool = Field(default=False)  # EXP-07, off until owner approves
    feature_lakebase_cdf: bool = False  # ARC-02 history feed via CDF (Preview) vs snapshot diff job
    feature_image_embeddings: bool = False  # IMG-04
    feature_image_ai_match: bool = False  # IMG-03 tier 3, on once PLT-00 step 8 passes
    feature_channel_send: bool = False  # EXP-05/06: actually call retailer adapters; off until credentials and tests exist
    ai_mapping_confidence_threshold: float = 0.70  # IMP-02
    feature_ai_mapping_suggest: bool = False  # IMP-02: ask the classify endpoint for header mappings the fuzzy matcher missed
    history_hot_years: float = 2.0  # GOV-02: history rows older than this leave Lakebase once copied to Delta
    app_base_url: str = ""  # DM-07/DM-09 digest links, for example https://pim-xxxx.databricksapps.com

    @property
    def is_databricks(self) -> bool:
        return self.env == "databricks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
