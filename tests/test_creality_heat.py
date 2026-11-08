"""Verify heater control using an isolated loopback printer and PrintGuard engine."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from printguard.engine.integrations import creality_stock as m
from tests.fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.engine.integrations import INTEGRATIONS


class HeatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.raw = {
            "model": "F003",
            "state": 0,
            "connect": 1,
            "nozzleTemp": 23,
            "targetNozzleTemp": 0,
            "maxNozzleTemp": 300,
            "bedTemp0": 24,
            "targetBedTemp0": 0,
            "maxBedTemp": 110,
        }
        self.mode = "confirm"
        self.commands = []
        self.connections = 0
        self.inflight = 0
        self.max_inflight = 0
        self.adapter = m.CrealityStockAdapter()
        self.server = await serve(self.handler, "127.0.0.1", 0, ping_interval=None)
        self.config = {
            "host": "127.0.0.1",
            "port": str(self.server.sockets[0].getsockname()[1]),
            "allow_heat": True,
            "allow_pause": True,
            "allow_resume": False,
        }

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, socket):
        self.connections += 1
        try:
            if self.mode == "quiet":
                await socket.wait_closed()
                return
            if self.mode == "partial":
                await socket.send(
                    json.dumps(
                        {"model": "F003", "state": self.raw["state"], "connect": 1}
                    )
                )
                await asyncio.sleep(0.01)
            await socket.send(json.dumps(self.raw))
            async for text in socket:
                message = json.loads(text)
                self.commands.append(message)
                params = message["params"]
                heater = "nozzle" if "nozzleTempControl" in params else "bed"
                target = (
                    params["nozzleTempControl"]
                    if heater == "nozzle"
                    else params["bedTempControl"]["val"]
                )
                actual_key, target_key, _ = m.HEATER_FIELDS[heater]
                if self.mode == "disconnect":
                    await socket.close()
                    return
                await socket.send(text)
                if self.mode == "ack-only":
                    continue
                if self.mode == "malformed":
                    await socket.send("not-json")
                    continue
                if self.mode == "actual-only":
                    change = {actual_key: target}
                elif self.mode == "wrong-target":
                    change = {target_key: target - 1}
                elif self.mode == "other-heater":
                    change = {
                        m.HEATER_FIELDS["bed" if heater == "nozzle" else "nozzle"][
                            1
                        ]: target
                    }
                elif self.mode == "offline":
                    change = {target_key: target, "connect": 0}
                elif self.mode == "wrong-model":
                    change = {target_key: target, "model": "F004"}
                elif self.mode == "invalid-target":
                    change = {target_key: False}
                else:
                    change = {
                        target_key: str(target) if self.mode == "string" else target
                    }
                self.inflight += 1
                self.max_inflight = max(self.max_inflight, self.inflight)
                await asyncio.sleep(0.01)
                self.raw.update(change)
                await socket.send(json.dumps(change))
                self.inflight -= 1
        except ConnectionClosed:
            pass

    async def http(self, *args, **kwargs):
        raise AssertionError("Unexpected HTTP call")

    async def heat(self, heater="nozzle", target=220, config=None):
        await self.adapter.heat(
            self.http, self.config if config is None else config, heater, target
        )

    async def test_nozzle_message_and_setpoint_confirmation(self):
        await self.heat()
        self.assertEqual(
            self.commands, [{"method": "set", "params": {"nozzleTempControl": 220}}]
        )
        self.assertEqual(self.raw["targetNozzleTemp"], 220)
        self.assertEqual(
            self.raw["nozzleTemp"],
            23,
            "Only the target is confirmed, not reaching temperature",
        )

    async def test_bed_message_uses_bed_zero(self):
        await self.heat("bed", 60)
        self.assertEqual(
            self.commands,
            [{"method": "set", "params": {"bedTempControl": {"num": 0, "val": 60}}}],
        )
        self.assertEqual(self.raw["targetBedTemp0"], 60)

    async def test_heaters_can_be_switched_off(self):
        self.raw.update(targetNozzleTemp=220, targetBedTemp0=60)
        await self.heat("nozzle", 0)
        await self.heat("bed", 0)
        self.assertEqual(
            self.commands,
            [
                {"method": "set", "params": {"nozzleTempControl": 0}},
                {"method": "set", "params": {"bedTempControl": {"num": 0, "val": 0}}},
            ],
        )

    async def test_fractional_target_is_preserved(self):
        await self.heat("nozzle", 215.5)
        self.assertEqual(self.commands[0]["params"]["nozzleTempControl"], 215.5)

    async def test_requires_explicit_heat_enable_before_connecting(self):
        for value in (False, None, "true", 1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "disabled"),
            ):
                await self.heat(config={**self.config, "allow_heat": value})
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await self.heat(
                config={k: v for k, v in self.config.items() if k != "allow_heat"}
            )
        self.assertEqual(self.connections, 0)

    async def test_heat_permission_is_independent_of_pause_and_resume(self):
        await self.heat(
            config={**self.config, "allow_pause": False, "allow_resume": False}
        )
        self.assertEqual(len(self.commands), 1)

    async def test_invalid_heater_and_targets_never_connect(self):
        invalid = [("chamber", 30), ("nozzle", -1), ("nozzle", 300.1), ("bed", 110.1)]
        invalid += [
            ("nozzle", x)
            for x in (
                True,
                False,
                None,
                "220",
                float("nan"),
                float("inf"),
                -float("inf"),
                10**1000,
            )
        ]
        for heater, target in invalid:
            with (
                self.subTest(heater=heater, target=target),
                self.assertRaises(ValueError),
            ):
                await self.heat(heater, target)
        self.assertEqual(self.connections, 0)

    async def test_model_limits_are_accepted(self):
        await self.heat("nozzle", 300)
        await self.heat("bed", 110)
        self.assertEqual(len(self.commands), 2)

    async def test_lower_reported_firmware_limit_is_respected(self):
        self.raw.update(maxNozzleTemp="260", maxBedTemp="100")
        for heater, target in (("nozzle", 270), ("bed", 105)):
            with (
                self.subTest(heater=heater),
                self.assertRaisesRegex(ValueError, "reported limit"),
            ):
                await self.heat(heater, target)
        self.assertEqual(self.commands, [])

    async def test_missing_optional_maximum_uses_model_limit(self):
        self.raw.pop("maxNozzleTemp")
        await self.heat()
        self.assertEqual(len(self.commands), 1)

    async def test_matching_target_is_a_no_op(self):
        self.raw["targetNozzleTemp"] = "220"
        await self.heat()
        self.assertEqual(self.commands, [])

    async def test_partial_initial_report_waits_for_heater_fields(self):
        self.mode = "partial"
        await self.heat()
        self.assertEqual(len(self.commands), 1)

    async def test_missing_heater_times_out_without_command(self):
        self.raw.pop("nozzleTemp")
        with (
            patch.object(m, "HEAT_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "no target sent"),
        ):
            await self.heat()
        self.assertEqual(self.commands, [])

    async def test_invalid_initial_heater_report_is_rejected(self):
        self.raw["targetNozzleTemp"] = None
        with self.assertRaisesRegex(RuntimeError, "valid nozzle heater"):
            await self.heat()
        self.assertEqual(self.commands, [])

    async def test_offline_or_wrong_model_receives_no_command(self):
        self.raw["connect"] = 0
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await self.heat()
        self.raw.update(connect=1, model="F004")
        with self.assertRaisesRegex(RuntimeError, "Unexpected printer model"):
            await self.heat()
        self.assertEqual(self.commands, [])

    async def test_fault_blocks_heating_but_allows_switching_off(self):
        self.raw.update(state=3, targetNozzleTemp=220)
        with self.assertRaisesRegex(RuntimeError, "reports an error"):
            await self.heat("nozzle", 230)
        self.assertEqual(self.commands, [])
        await self.heat("nozzle", 0)
        self.assertEqual(
            self.commands, [{"method": "set", "params": {"nozzleTempControl": 0}}]
        )

    async def test_printing_and_paused_jobs_allow_manual_temperature_changes(self):
        for state, target in ((1, 220), (5, 210)):
            self.raw["state"] = state
            await self.heat("nozzle", target)
        self.assertEqual(len(self.commands), 2)

    async def test_numeric_string_confirmation_is_accepted(self):
        self.mode = "string"
        await self.heat()
        self.assertEqual(self.raw["targetNozzleTemp"], "220")

    async def test_ack_actual_other_heater_or_wrong_target_does_not_confirm(self):
        for mode in (
            "ack-only",
            "actual-only",
            "other-heater",
            "wrong-target",
            "invalid-target",
        ):
            self.raw.update(targetNozzleTemp=0, nozzleTemp=23)
            self.mode = mode
            with (
                self.subTest(mode=mode),
                patch.object(m, "HEAT_TIMEOUT_S", 0.15),
                self.assertRaisesRegex(RuntimeError, "sent but not confirmed"),
            ):
                await self.heat()
        self.assertEqual(len(self.commands), 5)

    async def test_disconnection_after_send_is_not_success(self):
        self.mode = "disconnect"
        with self.assertRaises(ConnectionClosed):
            await self.heat()
        self.assertEqual(len(self.commands), 1)

    async def test_bad_reports_after_send_are_not_success(self):
        for mode, error in (
            ("offline", RuntimeError),
            ("wrong-model", RuntimeError),
            ("malformed", ValueError),
        ):
            self.raw.update(model="F003", connect=1, targetNozzleTemp=0)
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(error):
                await self.heat()
        self.assertEqual(len(self.commands), 3)

    async def test_quiet_printer_times_out_without_command(self):
        self.mode = "quiet"
        with (
            patch.object(m, "HEAT_TIMEOUT_S", 0.15),
            self.assertRaisesRegex(RuntimeError, "no target sent"),
        ):
            await self.heat()
        self.assertEqual(self.commands, [])

    async def test_concurrent_targets_are_serialized(self):
        await asyncio.gather(self.heat("nozzle", 220), self.heat("bed", 60))
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(self.max_inflight, 1)

    async def test_concurrent_identical_targets_send_once(self):
        await asyncio.gather(self.heat(), self.heat())
        self.assertEqual(len(self.commands), 1)

    async def test_engine_preheat_and_cooldown_use_existing_controls(self):
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
                self.assertTrue(
                    next(
                        a
                        for a in engine.state_event()["integrations"]
                        if a["id"] == self.adapter.id
                    )["heater_control"]
                )
                await engine.request(
                    {"cmd": "printer.heat", "id": printer.id, "nozzle": 220, "bed": 60}
                )
                self.assertEqual(
                    printer.device_state["nozzle"], {"actual": 23.0, "target": 220.0}
                )
                self.assertEqual(
                    printer.device_state["bed"], {"actual": 24.0, "target": 60.0}
                )
                await engine.request(
                    {"cmd": "printer.heat", "id": printer.id, "nozzle": 0, "bed": 0}
                )
                self.assertEqual(printer.device_state["nozzle"]["target"], 0)
                self.assertEqual(printer.device_state["bed"]["target"], 0)
                self.assertEqual(len(self.commands), 4)
                self.assertIs(printer.config["allow_resume"], False)
            finally:
                await engine.stop()

    async def test_engine_reports_unconfirmed_temperature_change(self):
        self.mode = "ack-only"
        platform = FakePlatform()
        engine = Engine(platform)
        with (
            patch.dict(INTEGRATIONS, {self.adapter.id: self.adapter}),
            patch.object(m, "HEAT_TIMEOUT_S", 0.15),
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
                with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                    await engine.request(
                        {"cmd": "printer.heat", "id": printer.id, "nozzle": 220}
                    )
                self.assertEqual(len(self.commands), 1)
            finally:
                await engine.stop()
