"""Stored credentials: what the state snapshot shows of them and how an edit keeps them.

A printer's or notifier's config, the MQTT settings and a camera source hold
keys, passwords and logins inside addresses. None of them leaves the engine,
so the snapshot every transport reads carries each config without its secret
fields and with its URLs scrubbed, beside the names of the secrets that are
stored. An edit made from that snapshot cannot send them back, so a secret it
leaves blank is kept.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

from .notifiers import NOTIFIERS
from .reports import is_url, scrub_catalogue_url, scrub_url, scrub_urls

ADDRESS_FIELDS = ("base_url", "host", "port", "url")
"""The config fields that say where a stored secret is sent."""
MQTT_SECRETS = {"password": "Password"}
SOURCE_SECRETS = frozenset({"access_code"})


def public_config(config: dict[str, Any], secrets: Collection[str]) -> dict[str, Any]:
    """Drops a config's secret fields and scrubs the URLs left.

    Args:
        config: A stored printer, notifier or MQTT config, or a camera source.
        secrets: The fields that hold a credential outright.

    Returns:
        The config as the snapshot shows it.
    """
    return scrub_urls({key: value for key, value in config.items() if key not in secrets})


def secrets_set(config: dict[str, Any], secrets: Collection[str]) -> list[str]:
    """Names the secret fields of a config that hold a stored value, sorted."""
    return sorted(key for key in secrets if config.get(key))


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """The settings as the snapshot shows them.

    A notifier this version has no adapter for is left out whole, since
    nothing declares which of its fields are secret.

    Args:
        settings: The engine's stored settings.

    Returns:
        The settings with every notifier config and the MQTT config made
        public and the catalogue address scrubbed.
    """
    return {
        **settings,
        "notifiers": {
            provider: public_config(config, NOTIFIERS[provider].secret_keys())
            for provider, config in settings["notifiers"].items()
            if provider in NOTIFIERS
        },
        "mqtt": public_config(settings["mqtt"], MQTT_SECRETS),
        "catalogue_url": scrub_catalogue_url(settings["catalogue_url"]),
    }


def settings_secrets_set(settings: dict[str, Any]) -> dict[str, Any]:
    """Names the secrets the settings hold, for the snapshot's ``secrets_set``.

    Args:
        settings: The engine's stored settings.

    Returns:
        The stored secret fields of each known notifier, and of MQTT.
    """
    return {
        "notifiers": {
            provider: secrets_set(config, NOTIFIERS[provider].secret_keys())
            for provider, config in settings["notifiers"].items()
            if provider in NOTIFIERS
        },
        "mqtt": secrets_set(settings["mqtt"], MQTT_SECRETS),
    }


def keep_url(sent: Any, stored: Any, scrubbed: Callable[[str], str] = scrub_url) -> Any:
    """Gives the stored address when the one sent is that address as the snapshot shows it."""
    return stored if is_url(stored) and sent == scrubbed(stored) else sent


def _address(config: dict[str, Any]) -> tuple[Any, ...]:
    """Where a config points, with an absent port read as the default one, so typing it is not a move."""
    port = config.get("port") or 1883
    return tuple(port if field == "port" else config.get(field) for field in ADDRESS_FIELDS)


def keep_stored(config: dict[str, Any], stored: dict[str, Any], secrets: Mapping[str, str]) -> dict[str, Any]:
    """Puts back the credentials a client could not have read.

    A secret is only put back for the address it was stored with, or an edit
    could point a printer or the broker somewhere else and have the hub
    present the key there.

    Args:
        config: The config a client sent.
        stored: The config the engine holds for the same thing.
        secrets: The fields its schema marks secret, each with the title the
            dashboard labels it with.

    Returns:
        The client's config, with each secret field it left out or blank and
        each URL it sent back scrubbed taken from the stored one. A secret
        field sent as null is cleared, which is the one way to remove one.

    Raises:
        ValueError: If the address changed and a stored secret was left out
            or blank.
    """
    kept = {key: stored[key] for key in secrets if key in stored and config.get(key, "") == ""}
    cleared = {key: "" for key in secrets if key in config and config[key] is None}
    unscrubbed = {key: keep_url(value, stored.get(key)) for key, value in config.items()}
    merged = {**unscrubbed, **kept, **cleared}
    held = sorted(key for key, value in kept.items() if value)
    if held and _address(merged) != _address(stored):
        raise ValueError(f"send {' and '.join(secrets[key].partition(' (')[0] for key in held)} again, since a stored secret is only kept for the address it was saved with")
    return merged
