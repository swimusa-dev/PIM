"""Entry point used by app.yaml. Binds 0.0.0.0:$DATABRICKS_APP_PORT (PLT-00) [D5]."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run("pim.main:app", host="0.0.0.0", port=port, workers=1, log_level="info", proxy_headers=True)
