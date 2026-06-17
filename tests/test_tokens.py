"""Engine token lifecycle: minting, hashed persistence and revocation."""

from __future__ import annotations

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.engine.tokens import hash_secret


async def test_tokens_are_minted_hashed_and_revocable() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        events = await engine.request({"cmd": "token.create", "name": "ci", "scope": "manage"})
        created = next(e for e in events if e.get("event") == "token_created")
        secret = created["token"]
        assert secret.startswith("pg_")

        listed = engine.state_event()["tokens"]
        assert listed == [{"id": created["id"], "name": "ci", "scope": "manage", "hint": created["hint"], "created": created["created"]}]
        assert "token" not in listed[0] and "hash" not in listed[0]
        assert engine.token_scopes() == {hash_secret(secret): "manage"}

        await engine.request({"cmd": "token.remove", "id": created["id"]})
        assert engine.state_event()["tokens"] == []
        assert engine.token_scopes() == {}
    finally:
        await engine.stop()


async def test_issued_tokens_survive_a_restart() -> None:
    platform = FakePlatform()
    engine = Engine(platform)
    await engine.start()
    events = await engine.request({"cmd": "token.create", "name": "agent", "scope": "read"})
    secret = next(e["token"] for e in events if e.get("event") == "token_created")
    await engine.stop()

    restored = Engine(platform)
    await restored.start()
    try:
        assert restored.token_scopes() == {hash_secret(secret): "read"}
    finally:
        await restored.stop()
