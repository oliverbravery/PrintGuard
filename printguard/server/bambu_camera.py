"""Bambu Lab chamber-camera reader for the A1 and P1 series (hub mode).

X1- and H2-series printers expose the chamber camera over RTSP, but the A1,
A1 mini, P1P and P1S stream it over a proprietary protocol on port 6000: a
TLS socket, an 80-byte authentication handshake, then repeating frames each of
a 16-byte header (whose first four bytes are the little-endian JPEG length)
followed by the JPEG payload.

BambuJpegStream presents that socket to PyAV as a plain MJPEG byte stream, the
framing headers stripped, so the same AVSource that reads any other source can
decode it for inference and republish it to MediaMTX for viewers.

Protocol reference: https://github.com/Doridian/OpenBambuAPI/blob/main/jpeg.md
"""

from __future__ import annotations

import socket
import ssl
import struct
from typing import Any

PORT = 6000
USERNAME = "bblp"
CONNECT_TIMEOUT_S = 5.0
_HEADER_BYTES = 16


def _auth_packet(access_code: str) -> bytes:
    """The 80-byte handshake: a 16-byte header then bblp and the access code."""
    return (
        struct.pack("<IIII", 0x40, 0x3000, 0, 0)
        + USERNAME.encode("ascii").ljust(32, b"\x00")
        + access_code.encode("ascii")[:32].ljust(32, b"\x00")
    )


class BambuJpegStream:
    """Blocking file-like over the camera socket, yielding concatenated JPEGs."""

    def __init__(self, sock: Any) -> None:
        self._sock = sock
        self._buffer = bytearray()

    def read(self, size: int = -1) -> bytes:
        if not self._buffer:
            payload = self._next_jpeg()
            if not payload:
                return b""
            self._buffer += payload
        cut = len(self._buffer) if size < 0 else min(size, len(self._buffer))
        out = bytes(self._buffer[:cut])
        del self._buffer[:cut]
        return out

    def _next_jpeg(self) -> bytes | None:
        header = self._recv(_HEADER_BYTES)
        if not header:
            return None
        return self._recv(int.from_bytes(header[:4], "little"))

    def _recv(self, count: int) -> bytes | None:
        chunk = bytearray()
        while len(chunk) < count:
            part = self._sock.recv(count - len(chunk))
            if not part:
                return None
            chunk += part
        return bytes(chunk)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def open_bambu_jpeg_stream(host: str, access_code: str) -> BambuJpegStream:
    """Connects, authenticates and returns the chamber camera's JPEG stream."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, PORT), timeout=CONNECT_TIMEOUT_S)
    sock = context.wrap_socket(raw, server_hostname=host)
    sock.sendall(_auth_packet(access_code))
    return BambuJpegStream(sock)
