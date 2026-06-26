"""Server platform stream handling."""

from __future__ import annotations


def test_callable_mjpeg_sources_limit_pyav_probe(monkeypatch) -> None:
    from printguard.server import platform

    opened = []

    class Pipe:
        pass

    pipe = Pipe()

    def fake_open(target, *, format, options, **kwargs):
        opened.append((target, format, options))
        return "container"

    monkeypatch.setattr(platform.av, "open", fake_open)

    source = object.__new__(platform.AVSource)
    source._source = lambda: pipe
    source._publish_url = None

    container, returned_pipe = source._open()

    assert container == "container"
    assert returned_pipe is pipe
    assert opened == [(pipe, "mjpeg", platform.MJPEG_LIVE_OPTIONS)]
    assert opened[0][2]["analyzeduration"] == "0"
    assert opened[0][2]["probesize"] == "32"
