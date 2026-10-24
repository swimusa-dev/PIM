"""File storage seam: local filesystem in development, Unity Catalog Volumes through the Files API in Databricks
(IMP-01 uploads, EXP-13 packages, EXP-05 payloads) [D15][D16]. Chosen by path prefix: `/Volumes/...` uses the API."""

from __future__ import annotations

import io
from pathlib import Path


class Storage:
    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/")
        self.is_volume = self.root.startswith("/Volumes/")

    def path(self, *parts: str) -> str:
        segments: list[str] = []
        for part in parts:
            for seg in part.replace("\\", "/").split("/"):
                if seg in ("", "."):
                    continue
                if seg == "..":
                    raise ValueError("Path traversal rejected")
                segments.append(seg)
        return "/".join([self.root, *segments])

    def write(self, rel: str, data: bytes) -> str:
        full = self.path(rel)
        if self.is_volume:
            from databricks.sdk import WorkspaceClient

            WorkspaceClient().files.upload(full, io.BytesIO(data), overwrite=True)
        else:
            p = Path(full)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return full

    def read(self, full: str) -> bytes:
        if full.startswith("/Volumes/"):
            from databricks.sdk import WorkspaceClient

            resp = WorkspaceClient().files.download(full)
            return resp.contents.read()
        return Path(full).read_bytes()

    def exists(self, full: str) -> bool:
        if full.startswith("/Volumes/"):
            from databricks.sdk import WorkspaceClient

            try:
                WorkspaceClient().files.get_metadata(full)
                return True
            except Exception:  # noqa: BLE001
                return False
        return Path(full).exists()
