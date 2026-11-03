"""Ultimaker integration over the printer's local HTTP APIs.

Every networked Ultimaker (Ultimaker 3 and 3 Extended, S3, S5, S7 and
Factor 4) serves two APIs on port 80. ``/api/v1`` describes the printer
itself, and its reads need no authentication. ``/cluster-api/v1`` is the one
Cura's LAN printing uses to queue, pause, resume and abort jobs, also without
authentication. The ``/api/v1`` writes need a digest key the user approves on
the printer's touchscreen, so this adapter uses none of them and leaves
heater targets alone.

Each printer is registered by its own address and serves its camera as MJPEG
on port 8080, the URL Cura builds for it.

API reference: served by each printer at ``/docs/api/``
Cura's client: https://github.com/Ultimaker/Cura/blob/main/plugins/UM3NetworkPrinting/src/Network/ClusterApiClient.py
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..adapters import multipart_form
from .base import DeviceAction, DeviceState, DeviceStatus, Heater, HttpFn, IntegrationAdapter, require_reply

_UPLOAD_TIMEOUT_S = 180.0
_CAMERA_PORT = 8080
_ACTIONS = {DeviceAction.PAUSE: "pause", DeviceAction.RESUME: "print", DeviceAction.CANCEL: "abort"}
_PRINTER_STATUS = {
    "idle": DeviceStatus.IDLE,
    "printing": DeviceStatus.PRINTING,
    "error": DeviceStatus.ERROR,
}
"""The printer's own status, read when it has no active job. Booting and maintenance say nothing about a print."""
_JOB_STATUS = {
    "sent_to_printer": DeviceStatus.PRINTING,
    "pre_print": DeviceStatus.PRINTING,
    "printing": DeviceStatus.PRINTING,
    "resuming": DeviceStatus.PRINTING,
    "pausing": DeviceStatus.PAUSED,
    "paused": DeviceStatus.PAUSED,
    "post_print": DeviceStatus.IDLE,
    "wait_cleanup": DeviceStatus.IDLE,
    "finished": DeviceStatus.IDLE,
}
"""The active job's status. A finished job waits on the printer until someone confirms the bed is clear."""
_ENDED = ("aborted", "failed")
"""Prefixes of a job that stopped early, such as ``aborted_wait_cleanup``, which also waits for the bed to be cleared."""


def _base(config: dict[str, Any]) -> str:
    return str(config["base_url"]).rstrip("/")


def _job_status(text: str) -> DeviceStatus:
    return _JOB_STATUS.get(text) or (DeviceStatus.IDLE if text.startswith(_ENDED) else DeviceStatus.UNKNOWN)


class UltimakerAdapter(IntegrationAdapter):
    """Talks to an Ultimaker printer's local APIs, unauthenticated as Cura does."""

    id = "ultimaker"
    label = "Ultimaker"
    docs_url = "https://github.com/Ultimaker/Cura/blob/main/plugins/UM3NetworkPrinting/src/Network/ClusterApiClient.py"
    setup_hint = "Use the IP address shown on the printer under Preferences > Network. The printer's API has no password, so keep it on a network you trust."
    experimental = True
    formats = ("gcode",)
    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.1.60",
            },
        },
        "required": ["base_url"],
    }

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Reads the printer and its heaters from /api/v1/printer and the active job from the cluster API.

        A job's elapsed and total seconds give its progress and time left, as
        Cura works them out.

        Raises:
            RuntimeError: If either API answers with anything but its own reply.
        """
        status, printer = await http("GET", f"{_base(config)}/api/v1/printer")
        require_reply("Ultimaker", "the printer's state", status, status == 200 and isinstance(printer, dict) and "heads" in printer)
        job = await self._active_job(http, config)
        hotend = printer["heads"][0]["extruders"][0]["hotend"]["temperature"]
        bed = printer["bed"]["temperature"]
        heaters = {
            "nozzle": Heater.reported(hotend.get("current"), hotend.get("target")),
            "bed": Heater.reported(bed.get("current"), bed.get("target")),
        }
        if not job:
            return DeviceState(_PRINTER_STATUS.get(str(printer.get("status")), DeviceStatus.UNKNOWN), **heaters)
        elapsed, total = float(job.get("time_elapsed") or 0), float(job.get("time_total") or 0)
        return DeviceState(
            _job_status(str(job.get("status"))),
            min(elapsed / max(total, 1.0), 1.0) * 100,
            job.get("name"),
            remaining_s=int(max(total - elapsed, 0)) if total else None,
            **heaters,
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Pauses, resumes or aborts the active job through /cluster-api/v1/print_jobs/{uuid}/action.

        Resume is the cluster API's ``print`` action, as Cura sends it.

        Raises:
            RuntimeError: If there is no active job, or the printer refuses the command.
        """
        job = await self._active_job(http, config)
        if not job:
            raise RuntimeError(f"Ultimaker printer has no active job to {action.value}")
        status, _ = await http(
            "PUT",
            f"{_base(config)}/cluster-api/v1/print_jobs/{job['uuid']}/action",
            json={"action": _ACTIONS[action]},
        )
        require_reply("Ultimaker", action.value, status, status in (200, 204))

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Queues the file through /cluster-api/v1/print_jobs/, which an idle printer starts.

        A printer still holding its last print waits for someone to confirm on
        its screen that the bed is clear before it starts.

        Raises:
            RuntimeError: If the printer refuses the file.
        """
        headers, body = multipart_form({"owner": "PrintGuard"}, "file", filename, data, "application/octet-stream")
        status, _ = await http(
            "POST",
            f"{_base(config)}/cluster-api/v1/print_jobs/",
            headers=headers,
            data=body,
            timeout=_UPLOAD_TIMEOUT_S,
        )
        require_reply("Ultimaker", filename, status, status in (200, 201))

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Exposes the printer's MJPEG stream on port 8080 of the registered host."""
        host = urlsplit(_base(config)).hostname
        url = urlunsplit(("http", f"{host}:{_CAMERA_PORT}", "/", "action=stream", ""))
        return [{"key": "camera", "name": "Ultimaker camera", "source": {"kind": "url", "url": url}}]

    async def _active_job(self, http: HttpFn, config: dict[str, Any]) -> dict[str, Any] | None:
        status, jobs = await http("GET", f"{_base(config)}/cluster-api/v1/print_jobs/printing")
        require_reply("Ultimaker", "its print jobs", status, status == 200 and isinstance(jobs, list))
        return jobs[0] if jobs else None
