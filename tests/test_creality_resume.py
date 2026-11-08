"""Test resume through loopback WebSockets and the real PrintGuard command path."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from printguard.engine.integrations import creality_stock as m
from tests.fakes import FakePlatform
from printguard.engine import engine as engine_module
from printguard.engine.engine import Engine
from printguard.engine.integrations import DeviceAction, DeviceStatus, INTEGRATIONS


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.raw = {"model": "F003", "state": 5, "connect": 1, "repoPlrStatus": 0}
        self.commands = []
        self.wire_messages = []
        self.connections = 0
        self.mode = "normal"
        self.delay = 0.01
        self.transitions = [{"state": 8}, {"nozzleTemp": 200}, {"state": 1}]
        self.adapter = m.CrealityStockAdapter()
        self.server = await serve(self.handler, "127.0.0.1", 0, ping_interval=None)
        self.config = {
            "host": "127.0.0.1",
            "port": str(self.server.sockets[0].getsockname()[1]),
            "allow_pause": True,
            "allow_resume": True,
        }

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def emit_transitions(self, socket):
        for change in self.transitions:
            await asyncio.sleep(self.delay)
            self.raw.update(change)
            await socket.send(json.dumps(change))

    async def handler(self, socket):
        self.connections += 1
        try:
            if self.mode == "quiet":
                await socket.wait_closed()
                return
            await socket.send(json.dumps(self.raw))
            if self.raw["state"] == 8:
                await self.emit_transitions(socket)
            async for message in socket:
                self.wire_messages.append(message)
                self.commands.append(json.loads(message))
                if self.mode == "disconnect":
                    await socket.close()
                    return
                if self.mode == "malformed":
                    await socket.send("not-json")
                    continue
                await socket.send(json.dumps({"method": "set", "params": {"pause": 0}}))
                await self.emit_transitions(socket)
        except ConnectionClosed:
            pass

    async def http(self, *args, **kwargs):
        raise AssertionError("Unexpected HTTP call")

    async def resume(self, config=None):
        await self.adapter.send(
            self.http, self.config if config is None else config, DeviceAction.RESUME
        )

    async def test_exact_resume_message_and_printing_confirmation(self):
        await self.resume()
        self.assertEqual(self.raw["state"], 1)
        self.assertEqual(self.wire_messages, ['{"method":"set","params":{"pause":0}}'])

    async def test_resume_requires_its_own_opt_in_before_connecting(self):
        config = {k: v for k, v in self.config.items() if k != "allow_resume"}
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await self.resume(config)
        for value in (False, None, "true", 1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "disabled"),
            ):
                await self.resume({**self.config, "allow_resume": value})
        self.assertEqual(self.connections, 0)

    async def test_resume_does_not_require_pause_permission(self):
        await self.resume({**self.config, "allow_pause": False})
        self.assertEqual(len(self.commands), 1)

    async def test_enabling_resume_does_not_enable_pause(self):
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await self.adapter.send(
                self.http, {**self.config, "allow_pause": False}, DeviceAction.PAUSE
            )
        self.assertEqual(self.connections, 0)

    async def test_already_printing_sends_nothing(self):
        self.raw["state"] = 1
        await self.resume()
        self.assertEqual(self.commands, [])

    async def test_restoring_waits_without_resending(self):
        self.raw["state"] = 8
        await self.resume()
        self.assertEqual(self.raw["state"], 1)
        self.assertEqual(self.commands, [])

    async def test_only_paused_or_restoring_jobs_can_resume(self):
        for state in (0, 2, 3, 4, 6, 7, 99, None, True):
            self.raw["state"] = state
            with (
                self.subTest(state=state),
                self.assertRaisesRegex(RuntimeError, "not paused or restoring"),
            ):
                await self.resume()
        self.assertEqual(self.commands, [])

    async def test_offline_printer_receives_no_command(self):
        self.raw["connect"] = 0
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await self.resume()
        self.assertEqual(self.commands, [])

    async def test_wrong_model_receives_no_command(self):
        self.raw["model"] = "F004"
        with self.assertRaisesRegex(RuntimeError, "Unexpected printer model"):
            await self.resume()
        self.assertEqual(self.commands, [])

    async def test_power_loss_recovery_is_not_normal_resume(self):
        for value in (1, "1", True):
            self.raw["repoPlrStatus"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "Power-loss recovery"),
            ):
                await self.resume()
        self.assertEqual(self.commands, [])

    async def test_sd_card_guard_blocks_resume(self):
        feature = "printInfo.sdCardGuardV2"
        for features in ([feature], json.dumps([feature]), "other," + feature):
            for status in (0, 2, "0", "2"):
                self.raw.update(features=features, sdCardStatus=status)
                with (
                    self.subTest(features=features, status=status),
                    self.assertRaisesRegex(RuntimeError, "SD-card guard"),
                ):
                    await self.resume()
        self.raw.update(sdCardStatus=1, sdCardResumeBlocked=True)
        with self.assertRaisesRegex(RuntimeError, "SD-card guard"):
            await self.resume()
        self.assertEqual(self.commands, [])

    async def test_sd_card_ready_allows_resume(self):
        self.raw.update(features=["printInfo.sdCardGuardV2"], sdCardStatus=1)
        await self.resume()
        self.assertEqual(len(self.commands), 1)

    async def test_legacy_sd_card_status_without_guard_does_not_block(self):
        self.raw["sdCardStatus"] = 0
        await self.resume()
        self.assertEqual(len(self.commands), 1)

    async def test_acknowledgement_without_printing_is_not_success(self):
        self.transitions = []
        with (
            patch.object(m, "RESUME_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(
                RuntimeError, "Resume was sent but PRINTING was not confirmed"
            ),
        ):
            await self.resume()
        self.assertEqual(len(self.commands), 1)

    async def test_restoring_or_temperature_updates_are_not_success(self):
        self.transitions = [{"state": 8}, {"nozzleTemp": 220}]
        with (
            patch.object(m, "RESUME_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "last reported state=8"),
        ):
            await self.resume()

    async def test_transient_idle_does_not_fail_before_printing(self):
        self.transitions = [{"state": 0}, {"state": 8}, {"state": "1"}]
        await self.resume()
        self.assertEqual(len(self.commands), 1)

    async def test_disconnection_after_sending_is_not_success(self):
        self.mode = "disconnect"
        with self.assertRaises(ConnectionClosed):
            await self.resume()
        self.assertEqual(len(self.commands), 1)

    async def test_offline_printing_report_is_not_success(self):
        self.transitions = [{"state": 1, "connect": 0}]
        with self.assertRaisesRegex(
            RuntimeError, "offline; PRINTING was not confirmed"
        ):
            await self.resume()

    async def test_changed_model_cannot_confirm_resume(self):
        self.transitions = [{"state": 1, "model": "F004"}]
        with self.assertRaisesRegex(RuntimeError, "expected CR-10 SE"):
            await self.resume()

    async def test_malformed_reply_cannot_confirm_resume(self):
        self.mode = "malformed"
        with self.assertRaises(ValueError):
            await self.resume()

    async def test_quiet_printer_times_out_without_sending(self):
        self.mode = "quiet"
        with (
            patch.object(m, "RESUME_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "did not confirm a printing state"),
        ):
            await self.resume()
        self.assertEqual(self.commands, [])

    async def test_concurrent_resumes_send_once(self):
        await asyncio.gather(self.resume(), self.resume())
        self.assertEqual(len(self.commands), 1)

    async def test_engine_resume_command_confirms_and_updates_status(self):
        platform = FakePlatform()
        engine = Engine(platform)
        with patch.dict(INTEGRATIONS, {self.adapter.id: self.adapter}):
            await engine.start()
            try:
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
                printer = next(iter(engine.printers.values()))
                await engine.request(
                    {"cmd": "printer.action", "id": printer.id, "action": "resume"}
                )
                self.assertEqual(
                    self.commands, [{"method": "set", "params": {"pause": 0}}]
                )
                self.assertEqual(
                    printer.device_state["status"], DeviceStatus.PRINTING.value
                )
            finally:
                await engine.stop()

    async def test_engine_allows_resume_to_outlast_normal_request_timeout(self):
        self.delay = 0.03
        self.adapter.slow_action_s = 0.5
        platform = FakePlatform()
        engine = Engine(platform)
        with patch.dict(INTEGRATIONS, {self.adapter.id: self.adapter}):
            await engine.start()
            try:
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
                printer = next(iter(engine.printers.values()))
                with patch.object(engine_module, "REQUEST_TIMEOUT_S", 0.02):
                    await engine.request(
                        {"cmd": "printer.action", "id": printer.id, "action": "resume"}
                    )
                self.assertEqual(
                    printer.device_state["status"], DeviceStatus.PRINTING.value
                )
                self.assertEqual(len(self.commands), 1)
            finally:
                await engine.stop()

    async def test_engine_reports_unconfirmed_resume_as_failure(self):
        self.transitions = []
        platform = FakePlatform()
        engine = Engine(platform)
        with (
            patch.dict(INTEGRATIONS, {self.adapter.id: self.adapter}),
            patch.object(m, "RESUME_TIMEOUT_S", 0.15),
        ):
            await engine.start()
            try:
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
                printer = next(iter(engine.printers.values()))
                with self.assertRaisesRegex(RuntimeError, "PRINTING was not confirmed"):
                    await engine.request(
                        {"cmd": "printer.action", "id": printer.id, "action": "resume"}
                    )
                self.assertEqual(len(self.commands), 1)
            finally:
                await engine.stop()
