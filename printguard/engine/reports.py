"""Sends anonymous bug reports to the project's Sentry feedback inbox.

A report is a single user-initiated POST of a Sentry envelope - a feedback
item carrying the user's description and optional contact email, plus a
sanitised diagnostics bundle, the engine and UI log tails and any files the
user attached. There is no SDK and no automatic telemetry: nothing leaves
the device unless the user submits a report, and every credential is
stripped before it does - structurally from the diagnostics, and by value
from the freeform log text, where a library error message may embed one.

The same scrubbed files can be packed into a zip the user downloads instead,
to inspect or send somewhere else themselves.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import sys
import time
import uuid
import zipfile
from collections.abc import Sequence
from datetime import datetime, timezone
from platform import platform as host_os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from . import logs
from .adapters import HttpFn
from .integrations import INTEGRATIONS
from .notifiers import NOTIFIERS
from .platform import Platform

if TYPE_CHECKING:
    from .engine import Engine

logger = logging.getLogger(__name__)

SENTRY_DSN = "https://b442a687c779ef1e4542cd610b867f54@o4511676954902528.ingest.de.sentry.io/4511676966502480"
REDACTED = "[redacted]"
MESSAGE_MAX = 4096
TIMEOUT_S = 20.0
SOURCE_KEYS = ("kind", "path", "device_id", "label")


def envelope_endpoint(dsn: str) -> str:
    """Derives the ingest envelope URL, authenticated by DSN key, from a DSN."""
    parts = urlsplit(dsn)
    return f"{parts.scheme}://{parts.hostname}/api/{parts.path.strip('/')}/envelope/?sentry_version=7&sentry_key={parts.username}"


def strip_userinfo(url: str) -> str:
    """Removes embedded credentials (user:pass@) from a URL."""
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def redact(config: dict[str, Any], secrets: set[str]) -> dict[str, Any]:
    """Replaces the named keys' values with a redaction marker."""
    return {key: REDACTED if key in secrets else value for key, value in config.items()}


def public_source(source: dict[str, Any]) -> dict[str, Any]:
    """Reduces a camera source to its non-sensitive shape.

    Sources are adapter-defined dicts that may carry credentials outright
    (the Bambu access code) or inside a URL, so only known-safe keys pass
    and URLs lose their userinfo.
    """
    slim = {key: source[key] for key in SOURCE_KEYS if key in source}
    if "url" in source:
        slim["url"] = strip_userinfo(str(source["url"]))
    return slim


def deployment(platform: Platform) -> str:
    """Names how this instance is deployed: desktop app, docker hub or local."""
    if platform.update_asset:
        return "desktop"
    return "local" if platform.mode == "local" else "docker"


def collect_secrets(engine: "Engine") -> set[str]:
    """Every configured credential value, for scrubbing freeform report text."""
    secrets: set[str] = set()
    for printer in engine.printers.values():
        adapter = INTEGRATIONS.get(printer.provider)
        keys = adapter.secret_keys() if adapter else set(printer.config)
        secrets |= {str(printer.config[key]) for key in keys if printer.config.get(key)}
    for provider, config in engine.settings.get("notifiers", {}).items():
        adapter = NOTIFIERS.get(provider)
        keys = adapter.secret_keys() if adapter else set(config)
        secrets |= {str(config[key]) for key in keys if config.get(key)}
    if (engine.settings.get("mqtt") or {}).get("password"):
        secrets.add(str(engine.settings["mqtt"]["password"]))
    for camera in engine.cameras.values():
        if camera.source.get("access_code"):
            secrets.add(str(camera.source["access_code"]))
        parts = urlsplit(str(camera.source.get("url") or ""))
        secrets |= {part for part in (parts.username, parts.password) if part}
    return secrets


def scrub(text: str, secrets: set[str]) -> str:
    """Replaces every occurrence of a credential value with the redaction marker."""
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def diagnostics(engine: "Engine") -> dict[str, Any]:
    """Builds the sanitised state bundle attached to every report.

    Carries the configuration shapes, scheduler stats and recent
    alert/warning/error events a maintainer needs to reproduce a bug,
    with every credential redacted: notifier and printer configs lose
    their schema-marked secret fields (unknown adapters lose the whole
    config), the MQTT password goes, camera sources are reduced to their
    non-sensitive shape and API tokens are omitted entirely.
    """
    settings = dict(engine.settings)
    settings["notifiers"] = {
        provider: redact(config, NOTIFIERS[provider].secret_keys()) if provider in NOTIFIERS else REDACTED
        for provider, config in settings.get("notifiers", {}).items()
    }
    if settings.get("mqtt"):
        settings["mqtt"] = redact(settings["mqtt"], {"password"})
    return {
        "version": engine.platform.version,
        "mode": engine.platform.mode,
        "deployment": deployment(engine.platform),
        "os": host_os(),
        "python": sys.version,
        "settings": settings,
        "cameras": [{**camera.public(), "source": public_source(camera.source)} for camera in engine.cameras.values()],
        "printers": [
            {
                **printer.public(),
                "config": redact(printer.config, INTEGRATIONS[printer.provider].secret_keys())
                if printer.provider in INTEGRATIONS
                else REDACTED,
            }
            for printer in engine.printers.values()
        ],
        "monitors": list(engine.monitors.values()),
        "stats": engine.scheduler.stats(),
        "update": engine.update,
        "recent_events": engine.recent_events(),
    }


def feedback_event(message: str, email: str | None, client: dict[str, Any], diag: dict[str, Any]) -> dict[str, Any]:
    """Builds the Sentry feedback event payload for a report."""
    feedback: dict[str, Any] = {"message": message[:MESSAGE_MAX]}
    if email:
        feedback["contact_email"] = email
    if client.get("url"):
        feedback["url"] = client["url"]
    contexts: dict[str, Any] = {"feedback": feedback}
    if client:
        contexts["client"] = client
    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": time.time(),
        "platform": "python",
        "level": "info",
        "release": f"printguard@{diag['version']}",
        "environment": diag["deployment"],
        "tags": {"mode": diag["mode"], "os": diag["os"]},
        "contexts": contexts,
    }


def report_files(
    *,
    diag: dict[str, Any],
    ui_logs: Sequence[str],
    secrets: set[str],
    attachments: Sequence[dict[str, Any]] = (),
) -> list[tuple[str, str, bytes]]:
    """Builds a report's files: diagnostics, both log tails and user attachments.

    The diagnostics JSON and both log tails are scrubbed of every value in
    ``secrets``, since an error string inside any of them may embed a
    credential the structural redaction cannot see.
    """
    files = [("diagnostics.json", "application/json", scrub(json.dumps(diag, indent=2), secrets).encode())]
    if logs.recent():
        files.append(("engine.log", "text/plain", scrub("\n".join(logs.recent()), secrets).encode()))
    if ui_logs:
        files.append(("ui.log", "text/plain", scrub("\n".join(str(line) for line in ui_logs), secrets).encode()))
    for attachment in attachments:
        files.append(
            (
                str(attachment["name"]),
                str(attachment.get("type") or "application/octet-stream"),
                base64.b64decode(attachment["data"]),
            )
        )
    return files


def archive(files: list[tuple[str, str, bytes]]) -> bytes:
    """Packs report files into a zip archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for filename, _content_type, payload in files:
            bundle.writestr(filename, payload)
    return buffer.getvalue()


def archive_name() -> str:
    """Names a downloaded archive after the moment it was taken."""
    return f"printguard-diagnostics-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"


def encode_envelope(event: dict[str, Any], attachments: list[tuple[str, str, bytes]]) -> bytes:
    """Serialises a feedback event and its attachments as a Sentry envelope."""
    lines = [
        json.dumps({"event_id": event["event_id"], "sent_at": datetime.now(timezone.utc).isoformat()}).encode(),
        json.dumps({"type": "feedback"}).encode(),
        json.dumps(event).encode(),
    ]
    for filename, content_type, payload in attachments:
        header = {
            "type": "attachment",
            "length": len(payload),
            "filename": filename,
            "content_type": content_type,
            "attachment_type": "event.attachment",
        }
        lines.append(json.dumps(header).encode())
        lines.append(payload)
    return b"\n".join(lines)


async def send_report(
    http: HttpFn,
    dsn: str,
    *,
    message: str,
    email: str | None,
    client: dict[str, Any],
    diag: dict[str, Any],
    attachments: Sequence[dict[str, Any]],
    ui_logs: Sequence[str],
    secrets: set[str],
) -> None:
    """Submits one bug report envelope to the feedback inbox.

    Args:
        http: Platform HTTP function.
        dsn: The Sentry DSN to report to.
        message: The user's description of the problem.
        email: Optional contact email for follow-up.
        client: UI-supplied context (url, user_agent, viewport).
        diag: The sanitised diagnostics bundle, attached as JSON.
        attachments: User-attached files as {name, type, data} with
            base64-encoded data.
        ui_logs: The UI's recent log lines; the engine's own tail is read
            from the logging module.
        secrets: Credential values to scrub, from ``collect_secrets``.

    Raises:
        ValueError: If the description is empty.
        RuntimeError: If the inbox does not accept the envelope.
    """
    if not message:
        raise ValueError("a description of the problem is required")
    files = report_files(diag=diag, ui_logs=ui_logs, secrets=secrets, attachments=attachments)
    event = feedback_event(message, email, client, diag)
    status, _ = await http(
        "POST",
        envelope_endpoint(dsn),
        headers={"Content-Type": "application/x-sentry-envelope"},
        data=encode_envelope(event, files),
        timeout=TIMEOUT_S,
    )
    if status >= 300:
        raise RuntimeError(f"the report was not accepted (HTTP {status})")
    logger.info("bug report sent (%d attachments)", len(files))
