"""EXP-09 file delivery: download (nothing to do), SFTP (paramiko, password or private key from an app secret
resource named in the transport profile), or email (SMTP settings from config). Every result is recorded on the
publish as a DeliveryResult; a misconfigured transport fails the delivery, never the publish."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import smtplib
from email.message import EmailMessage

from pim.adapters.base import NotConfigured
from pim.config import get_settings
from pim.models._common import utcnow

log = logging.getLogger(__name__)


def secret_value(secret_name: str | None) -> str | None:
    """App secret resources arrive as environment variables (GOV-05): `shopify-read-token` -> PIM_SHOPIFY_READ_TOKEN
    or the raw name; both spellings are tried."""
    if not secret_name:
        return None
    candidates = [secret_name, secret_name.upper().replace("-", "_"), "PIM_" + secret_name.upper().replace("-", "_")]
    for c in candidates:
        v = os.environ.get(c)
        if v:
            return v
    return None


def deliver(channel, files: list[tuple[str, bytes]], *, sftp_client=None, smtp_factory=None) -> dict:  # noqa: ANN001
    cfg = channel.config or {}
    transport = cfg.get("transport") or "download"
    result = {"transport": transport, "status": "skipped", "detail": "", "at": utcnow().isoformat(), "files": [n for n, _ in files]}
    if not files:
        result["detail"] = "nothing to deliver"
        return result
    try:
        if transport == "sftp":
            result["detail"] = _sftp(cfg.get("sftp") or {}, files, sftp_client)
            result["status"] = "delivered"
        elif transport == "email":
            result["detail"] = _email(cfg.get("email") or {}, channel.label, files, smtp_factory)
            result["status"] = "delivered"
        else:
            result["detail"] = "download transport: files are picked up from the publish page"
    except NotConfigured as exc:
        result["status"], result["detail"] = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("delivery failed")
        result["status"], result["detail"] = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
    return result


def _sftp(conf: dict, files: list[tuple[str, bytes]], client=None) -> str:  # noqa: ANN001
    host, user = conf.get("host"), conf.get("username")
    if not host or not user:
        raise NotConfigured("SFTP host and username are not set on the channel transport")
    path = (conf.get("path") or "/").rstrip("/") or "/"
    if client is None:
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover
            raise NotConfigured("paramiko is not installed") from exc
        secret = secret_value(conf.get("secret_name"))
        if not secret:
            raise NotConfigured(f"SFTP secret {conf.get('secret_name') or '(unset)'} is not bound as an app secret resource")
        pinned = str(conf.get("host_key") or "").strip()
        if not pinned:
            raise NotConfigured("SFTP host key is not pinned on the channel transport; paste the server's ssh-keyscan key or SHA256 fingerprint")
        transport = paramiko.Transport((host, int(conf.get("port") or 22)))
        try:
            # The server proves its identity before any credential leaves the app: the key it presents must match
            # the pinned host key, otherwise an impostor at the host name would receive the password or key exchange.
            transport.start_client(timeout=30)
            remote = transport.get_remote_server_key()
            if not host_key_matches(pinned, remote):
                raise NotConfigured(f"SFTP host key for {host} does not match the pinned key (got SHA256:{_sha256_fingerprint(remote)})")
            if secret.startswith("-----BEGIN"):
                key = paramiko.RSAKey.from_private_key(io.StringIO(secret))
                transport.auth_publickey(user, key)
            else:
                transport.auth_password(user, secret)
            client = paramiko.SFTPClient.from_transport(transport)
            try:
                _upload(client, path, files)
            finally:
                client.close()
        finally:
            transport.close()
        return f"{len(files)} file(s) uploaded to {host}:{path}"
    _upload(client, path, files)
    return f"{len(files)} file(s) uploaded to {host}:{path}"


def _upload(client, path: str, files: list[tuple[str, bytes]]) -> None:  # noqa: ANN001
    for name, data in files:
        with client.open(f"{path}/{name}", "wb") as fh:
            fh.write(data)


def _sha256_fingerprint(key) -> str:  # noqa: ANN001
    return base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def host_key_matches(pinned: str, key) -> bool:  # noqa: ANN001
    """`pinned` is either an ssh-keyscan line (`host ssh-ed25519 AAAA...`), the bare base64 key, or `SHA256:<fp>`."""
    pinned = pinned.strip()
    if pinned.upper().startswith("SHA256:"):
        return pinned.split(":", 1)[1].rstrip("=") == _sha256_fingerprint(key)
    tokens = [t for t in pinned.split() if t]
    candidates = {t for t in tokens if t.startswith("AAAA")} or set(tokens)
    return key.get_base64() in candidates


def _email(conf: dict, label: str, files: list[tuple[str, bytes]], smtp_factory=None) -> str:  # noqa: ANN001
    s = get_settings()
    to = [t for t in (conf.get("to") or []) if t]
    if not to:
        raise NotConfigured("No recipients on the channel transport")
    if not s.smtp_host and smtp_factory is None:
        raise NotConfigured("PIM_SMTP_HOST is not set")
    msg = EmailMessage()
    msg["Subject"] = conf.get("subject") or f"{label} product data feed from Swim USA PIM"
    msg["From"] = s.smtp_from or s.smtp_user or "pim@swimusa.com"
    msg["To"] = ", ".join(to)
    msg.set_content(f"Attached: {', '.join(n for n, _ in files)}. Generated by the Swim USA PIM.")
    for name, data in files:
        maintype, subtype = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet") if name.endswith(".xlsx") else ("text", "csv")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    factory = smtp_factory or (lambda: smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30))
    with factory() as smtp:
        if smtp_factory is None:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)
    return f"{len(files)} file(s) emailed to {', '.join(to)}"
