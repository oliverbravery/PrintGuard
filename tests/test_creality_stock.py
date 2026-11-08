"""Exercise the adapter and real PrintGuard watchdog against a loopback fake printer."""

from __future__ import annotations
import asyncio
import json
import unittest
from unittest.mock import patch
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from printguard.engine.integrations import INTEGRATIONS, DeviceAction, DeviceStatus
from printguard.engine.integrations import creality_stock as m
from tests.fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.engine import watchdog


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = 1
        self.model = "F003"
        self.mode = "confirm"
        self.commands = []
        self.connections = 0
        self.adapter = m.CrealityStockAdapter()
        self.server = await serve(self.handler, "127.0.0.1", 0, ping_interval=None)
        self.config = {
            "host": "127.0.0.1",
            "port": str(self.server.sockets[0].getsockname()[1]),
            "allow_pause": True,
        }

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, ws):
        self.connections += 1
        try:
            if self.mode == "quiet":
                await ws.wait_closed()
                return
            if self.mode == "malformed":
                await ws.send("not-json")
                await ws.wait_closed()
                return
            if self.mode == "partial":
                await ws.send(json.dumps({"model": self.model, "nozzleTemp": "220"}))
                await ws.send(
                    json.dumps(
                        {"state": self.state, "bedTemp0": "60", "printProgress": 14}
                    )
                )
            else:
                await ws.send(
                    json.dumps(
                        {
                            "model": self.model,
                            "state": self.state,
                            "connect": 1,
                            "printProgress": 14,
                            "printFileName": "/usr/data/printer_data/gcodes/test.gcode",
                            "printLeftTime": 100,
                            "nozzleTemp": "220",
                            "targetNozzleTemp": 220,
                            "bedTemp0": "60",
                            "targetBedTemp0": 60,
                        }
                    )
                )
            if self.mode == "pausing":
                await asyncio.sleep(0.02)
                self.state = 5
                await ws.send(json.dumps({"state": 5}))
            async for text in ws:
                data = json.loads(text)
                self.commands.append(data)
                if self.mode == "disconnect":
                    await ws.close()
                    return
                await ws.send(json.dumps({"method": "set", "params": {"pause": 1}}))
                if self.mode == "transient-idle":
                    await ws.send(json.dumps({"state": 0}))
                    await asyncio.sleep(0.02)
                    self.state = 5
                    await ws.send(json.dumps({"state": 5}))
                if self.mode == "idle-only":
                    await ws.send(json.dumps({"state": 0}))
                if self.mode == "confirm":
                    await ws.send(json.dumps({"state": 6}))
                    await asyncio.sleep(0.02)
                    self.state = 5
                    await ws.send(json.dumps({"state": 5}))
        except ConnectionClosed:
            pass

    async def http(self, *a, **k):
        raise AssertionError("Unexpected HTTP call")

    async def test_read_only(self):
        state = await self.adapter.fetch_state(self.http, self.config)
        self.assertEqual(state.status, DeviceStatus.PRINTING)
        self.assertEqual(state.job, "test.gcode")
        self.assertEqual(state.nozzle.actual, 220)
        self.assertEqual(state.bed.target, 60)
        self.assertEqual(self.commands, [])

    async def test_partial_snapshot(self):
        self.mode = "partial"
        state = await self.adapter.fetch_state(self.http, self.config)
        self.assertEqual(state.status, DeviceStatus.PRINTING)
        self.assertEqual(self.commands, [])

    async def test_disabled_before_connection(self):
        for value in [False, None, "true"]:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                await self.adapter.send(
                    self.http, {**self.config, "allow_pause": value}, DeviceAction.PAUSE
                )
        self.assertEqual(self.connections, 0)

    async def test_cancel_refused(self):
        with self.assertRaisesRegex(RuntimeError, "Cancel commands are disabled"):
            await self.adapter.send(self.http, self.config, DeviceAction.CANCEL)
        self.assertEqual(self.connections, 0)

    async def test_pause_is_confirmed(self):
        await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.state, 5)
        self.assertEqual(self.commands, [{"method": "set", "params": {"pause": 1}}])

    async def test_transient_idle_before_paused(self):
        self.mode = "transient-idle"
        await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.state, 5)
        self.assertEqual(len(self.commands), 1)

    async def test_idle_transition_alone_is_not_success(self):
        self.mode = "idle-only"
        with (
            patch.object(m, "ACTION_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "not confirmed"),
        ):
            await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(len(self.commands), 1)

    async def test_already_paused_is_not_sent_again(self):
        self.state = 5
        await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.commands, [])

    async def test_pausing_waits_without_resending(self):
        self.state = 6
        self.mode = "pausing"
        await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.state, 5)
        self.assertEqual(self.commands, [])

    async def test_ack_alone_is_not_success(self):
        self.mode = "ack-only"
        with (
            patch.object(m, "ACTION_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "not confirmed"),
        ):
            await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(len(self.commands), 1)

    async def test_disconnect_is_not_success(self):
        self.mode = "disconnect"
        with self.assertRaises(ConnectionClosed):
            await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)

    async def test_wrong_model_refused_before_command(self):
        self.model = "F004"
        with self.assertRaisesRegex(RuntimeError, "Unexpected printer model"):
            await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.commands, [])

    async def test_idle_refused(self):
        self.state = 0
        with self.assertRaisesRegex(RuntimeError, "not reporting an active"):
            await self.adapter.send(self.http, self.config, DeviceAction.PAUSE)
        self.assertEqual(self.commands, [])

    async def test_quiet_status_times_out(self):
        self.mode = "quiet"
        with patch.object(m, "FETCH_TIMEOUT_S", 0.15), self.assertRaises(TimeoutError):
            await self.adapter.fetch_state(self.http, self.config)

    async def test_malformed_status_does_not_become_idle(self):
        self.mode = "malformed"
        with self.assertRaises(ValueError):
            await self.adapter.fetch_state(self.http, self.config)

    async def test_unknown_transitions_stay_unknown(self):
        for state in [6, 7, 8, 99, None, True, "unrecognised"]:
            self.assertEqual(
                m.normalise({"model": "F003", "state": state}).status,
                DeviceStatus.UNKNOWN,
            )
        for state in [0, 2, 4]:
            self.assertEqual(
                m.normalise({"model": "F003", "state": state}).status, DeviceStatus.IDLE
            )

    async def test_engine_defect_reaches_pause_and_notification(self):
        await self.engine_case(False)

    async def test_engine_reports_unconfirmed_pause_failure(self):
        self.mode = "ack-only"
        with (
            patch.object(m, "ACTION_TIMEOUT_S", 0.15),
            patch.object(watchdog, "ACT_ATTEMPTS", 1),
            patch.object(watchdog, "ACT_RETRY_S", 0),
        ):
            await self.engine_case(True)

    async def engine_case(self, fail):
        platform = FakePlatform(infer_s=0.01, failing=False)
        engine = Engine(platform)
        events = []
        with patch.dict(INTEGRATIONS, {self.adapter.id: self.adapter}):
            await engine.start()
            engine.add_sink(events.append)
            try:
                await engine.handle(
                    {
                        "cmd": "settings.update",
                        "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}},
                    }
                )
                await engine.handle(
                    {
                        "cmd": "camera.add",
                        "name": "Synthetic camera",
                        "source": {"kind": "fake", "fps": 10},
                    }
                )
                await engine.handle(
                    {
                        "cmd": "printer.add",
                        "printer": {
                            "name": "Loopback fake",
                            "provider": self.adapter.id,
                            "config": self.config,
                        },
                    }
                )
                camera = next(iter(engine.cameras.values()))
                printer = next(iter(engine.printers.values()))
                await engine.handle(
                    {
                        "cmd": "monitor.add",
                        "monitor": {
                            "name": "Synthetic defect",
                            "camera_id": camera.id,
                            "printer_id": printer.id,
                            "enabled": True,
                            "on_defect": "pause",
                            "threshold": 0.75,
                            "consecutive": 3,
                            "notify": True,
                        },
                    }
                )
                await asyncio.sleep(0.5)
                self.assertEqual(self.commands, [])
                platform.failing = True
                for _ in range(100):
                    if any((e.get("event") == "alert" for e in events)):
                        break
                    await asyncio.sleep(0.05)
                alerts = [e for e in events if e.get("event") == "alert"]
                self.assertTrue(alerts, events[-5:])
                self.assertEqual(alerts[0]["action"], "failed" if fail else "pause")
                self.assertEqual(
                    self.commands, [{"method": "set", "params": {"pause": 1}}]
                )
                for _ in range(20):
                    if any(
                        (url == "http://ntfy/topic" for _, url in platform.http_calls)
                    ):
                        break
                    await asyncio.sleep(0.05)
                self.assertTrue(
                    any((url == "http://ntfy/topic" for _, url in platform.http_calls))
                )
                if fail:
                    self.assertTrue(
                        any(
                            (
                                "automatic pause failed" in e.get("message", "")
                                for e in events
                            )
                        )
                    )
                else:
                    self.assertEqual(self.state, 5)
            finally:
                await engine.stop()
