"""What the hub sends the training inbox, held to what the Worker accepts."""

from __future__ import annotations

import json
from typing import Any

from printguard.engine import feedback

EMOJI = "\U0001f600"


def test_a_printer_model_is_trimmed_to_80_characters_not_utf16_units() -> None:
    assert feedback.printer_model(EMOJI * 81) == EMOJI * 80
    assert len(feedback.printer_model("x" * 79 + EMOJI + "y")) == 80


def test_a_printer_model_keeps_its_words_and_loses_control_characters() -> None:
    assert feedback.printer_model("  Prusa \t MK4\x00\n ") == "Prusa MK4"
    assert feedback.printer_model(None) == ""


async def test_the_frame_header_is_plain_ascii_that_decodes_to_the_trimmed_model() -> None:
    sent: dict[str, Any] = {}

    async def http(method: str, url: str, **request: Any) -> tuple[int, Any]:
        sent.update(request)
        return 201, {}

    await feedback.put_frame(http, "token", b"jpeg", {"printer": feedback.printer_model(EMOJI * 100)})

    header = sent["headers"]["X-Frame"]
    assert header.isascii()
    assert len(json.loads(header)["printer"]) == feedback.PRINTER_MODEL_MAX
