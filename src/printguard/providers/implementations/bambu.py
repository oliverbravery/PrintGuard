"""BambuLabs printer provider implementation.

- MQTT: Port 8883 with TLS, username "bblp", password is LAN access_code
- Topics: device/{serial}/report (subscribe), device/{serial}/request (publish)
- X1/H2/P2S series: RTSP camera on port 322 (rtsps://bblp:{code}@{host}:322/streaming/live/1)
- P1/A1 series: TCP camera on port 6000 with TLS and 80-byte auth packet
"""

import asyncio
import json
import logging
import socket
import ssl
import struct
from typing import Any, Optional, Tuple

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from aiortc import MediaStreamTrack, RTCPeerConnection, VideoStreamTrack
from av import VideoFrame

from ..base import PrinterProvider
from ..registry import register

logger = logging.getLogger(__name__)


class BambuRTSPTrack(VideoStreamTrack):
    """RTSP video track for X1/P2S series (port 322)."""

    def __init__(self, host: str, access_code: str):
        super().__init__()
        self.url = f"rtsps://bblp:{access_code}@{host}:322/streaming/live/1"
        self._cap: Optional[cv2.VideoCapture] = None

    async def recv(self) -> VideoFrame:
        if self._cap is None:
            self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                raise RuntimeError("Failed to open RTSP stream")
        loop = asyncio.get_event_loop()
        ret, frame = await loop.run_in_executor(None, self._cap.read)
        if not ret:
            self._cap.release()
            self._cap = None
            raise RuntimeError("Failed to read frame")
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        pts, time_base = await self.next_timestamp()
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def stop(self):
        super().stop()
        if self._cap:
            self._cap.release()
            self._cap = None


class BambuTCPTrack(VideoStreamTrack):
    """TCP video track for P1/A1 series (port 6000 with TLS).

    Auth packet (80 bytes):
      [0:4]   payload_size = 0x40 (little-endian)
      [4:8]   type = 0x3000 (little-endian)
      [8:16]  reserved = 0
      [16:48] username "bblp" null-padded
      [48:80] access_code null-padded
    """

    def __init__(self, host: str, access_code: str):
        super().__init__()
        self.host = host
        self.access_code = access_code
        self._ssl_sock: Optional[ssl.SSLSocket] = None
        self._sock: Optional[socket.socket] = None

    def _build_auth_packet(self) -> bytes:
        packet = bytearray(80)
        struct.pack_into("<I", packet, 0, 0x40)
        struct.pack_into("<I", packet, 4, 0x3000)
        packet[16:16 + len("bblp")] = b"bblp"
        code_bytes = self.access_code[:32].encode("ascii")
        packet[48:48 + len(code_bytes)] = code_bytes
        return bytes(packet)

    async def _connect(self):
        if self._ssl_sock is not None:
            return
        loop = asyncio.get_event_loop()

        def do_connect():
            sock = socket.create_connection((self.host, 6000), timeout=10)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ssl_sock = ctx.wrap_socket(sock, server_hostname=self.host)
            ssl_sock.sendall(self._build_auth_packet())
            ssl_sock.setblocking(False)
            return sock, ssl_sock

        self._sock, self._ssl_sock = await loop.run_in_executor(None, do_connect)

    async def _read_frame(self) -> bytes:
        loop = asyncio.get_event_loop()
        header = b""
        while len(header) < 16:
            try:
                chunk = await loop.run_in_executor(
                    None, lambda: self._ssl_sock.recv(16 - len(header))
                )
                if not chunk:
                    raise RuntimeError("Connection closed")
                header += chunk
            except ssl.SSLWantReadError:
                await asyncio.sleep(0.01)
        payload_size = struct.unpack("<I", header[:4])[0]
        data = b""
        while len(data) < payload_size:
            try:
                chunk = await loop.run_in_executor(
                    None, lambda: self._ssl_sock.recv(min(8192, payload_size - len(data)))
                )
                if not chunk:
                    raise RuntimeError("Connection closed")
                data += chunk
            except ssl.SSLWantReadError:
                await asyncio.sleep(0.01)
        return data

    async def recv(self) -> VideoFrame:
        await self._connect()
        jpeg_data = await self._read_frame()
        frame = cv2.imdecode(np.frombuffer(jpeg_data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Failed to decode JPEG")
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        pts, time_base = await self.next_timestamp()
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def stop(self):
        super().stop()
        if self._ssl_sock:
            self._ssl_sock.close()
            self._ssl_sock = None
        if self._sock:
            self._sock.close()
            self._sock = None


@register("bambulabs")
class BambuLabsProvider(PrinterProvider):
    """Bambu Labs printer provider via local MQTT."""
    RTSP_MODELS = {"X1", "X1C", "X1E", "H2", "H2C", "H2D", "P2S"}

    def __init__(self, host: str, access_code: str, serial: str, model: str = "X1C"):
        self.host = host
        self.access_code = access_code
        self.serial = serial
        self.model = model.upper()
        self._state: dict[str, Any] = {}
        self._connected = asyncio.Event()
        self._pcs: set[RTCPeerConnection] = set()
        self._seq = 0
        self.client = mqtt.Client(client_id=f"printguard_{serial}")
        self.client.username_pw_set("bblp", access_code)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    @property
    def name(self) -> str:
        return "bambulabs"

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "connection_fields": [
                {"name": "host", "type": "string", "required": True, "label": "Printer IP"},
                {"name": "access_code", "type": "password", "required": True, "label": "Access Code"},
                {"name": "serial", "type": "string", "required": True, "label": "Serial Number"},
                {"name": "model", "type": "string", "required": True, "label": "Model"}
            ],
            "entity_fields": []
        }

    @classmethod
    async def validate_connection(cls, config: dict) -> bool:
        """Test connection to Bambu printer via MQTT."""
        host = config.get("host")
        access_code = config.get("access_code")
        serial = config.get("serial")
        if not all([host, access_code, serial]):
            return False
        connected = asyncio.Event()
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                connected.set()
        
        client = mqtt.Client()
        client.username_pw_set("bblp", access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.on_connect = on_connect
        
        try:
            client.connect_async(host, port=8883)
            client.loop_start()
            try:
                await asyncio.wait_for(connected.wait(), timeout=5.0)
                return True
            except asyncio.TimeoutError:
                return False
            finally:
                client.loop_stop()
                client.disconnect()
        except Exception as e:
            logger.error(f"Bambu validation failed: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(f"device/{self.serial}/report")
            self._connected.set()
        else:
            logger.error(f"MQTT connect failed: rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if "print" in data:
                self._state.update(data["print"])
        except Exception as e:
            logger.debug(f"Failed to parse MQTT message: {e}")

    async def connect(self) -> None:
        self.client.connect_async(self.host, port=8883)
        self.client.loop_start()
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=15)
        except asyncio.TimeoutError:
            self.client.loop_stop()
            raise RuntimeError("MQTT connection timeout")

    async def disconnect(self) -> None:
        for pc in list(self._pcs):
            await pc.close()
        self._pcs.clear()
        self.client.loop_stop()
        self.client.disconnect()
        self._connected.clear()

    async def is_printing(self) -> bool:
        state = self._state.get("gcode_state", "IDLE").upper()
        return state in ("PREPARE", "RUNNING")

    def _send(self, command: str):
        self._seq += 1
        payload = {"print": {"sequence_id": str(self._seq), "command": command, "param": ""}}
        self.client.publish(f"device/{self.serial}/request", json.dumps(payload))

    async def start(self) -> None:
        self._send("resume")

    async def pause(self) -> None:
        self._send("pause")

    async def resume(self) -> None:
        self._send("resume")

    async def stop(self) -> None:
        self._send("stop")

    async def get_camera_track(self) -> Tuple[Optional[MediaStreamTrack], Optional[RTCPeerConnection]]:
        pc = RTCPeerConnection()
        self._pcs.add(pc)
        if any(self.model.startswith(m) for m in self.RTSP_MODELS):
            track = BambuRTSPTrack(self.host, self.access_code)
        else:
            track = BambuTCPTrack(self.host, self.access_code)
        return track, pc