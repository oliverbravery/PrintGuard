"""Shared contract for pluggable service adapters.

Adapters (printer integrations, alert notifiers) reach external services
through the platform's HTTP function, so the tests can pin every request an
adapter makes.
"""

from __future__ import annotations

import uuid
from abc import ABC
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

HttpFn = Callable[..., Awaitable[tuple[int, Any]]]
KINDS: dict[str, tuple[type, str]] = {"string": (str, "text"), "boolean": (bool, "true or false")}
"""The Python type a schema property's JSON type holds, and how a refusal words it."""


def require_typed(config: dict[str, Any], properties: dict[str, dict[str, Any]]) -> None:
    """Refuses a config value that is not of the type its schema property declares, or not one of its ``enum``.

    A value left out or sent as null is not there to be checked, and a choice
    left blank is one not made yet.

    Args:
        config: The values supplied.
        properties: The schema properties they are held to, each with a
            ``title`` and a ``type`` that ``KINDS`` knows.

    Raises:
        ValueError: If a value is of another type or is not a choice its
            property offers, naming the first.
    """
    for key, prop in properties.items():
        kind, wording = KINDS[prop["type"]]
        value = config.get(key)
        if value is not None and type(value) is not kind:
            raise ValueError(f"{prop['title']} is {wording}")
        if value and "enum" in prop and value not in prop["enum"]:
            raise ValueError(f"{prop['title']} is one of {', '.join(prop['enum'])}")


class Adapter(ABC):
    """Base class for schema-configured service adapters.

    Attributes:
        id: Registry key and protocol identifier.
        label: Human-readable service name.
        docs_url: Link to the official API reference the adapter is built
            against; mandatory so reviewers can verify behaviour.
        desktop_only: Whether the adapter runs only in the desktop app (the
            hub packaged as a native window), where it can reach a service the
            headless container cannot - a local OS call. Set this True and it
            is offered only when the UI runs inside that app.
        experimental: Whether the adapter is new and not yet battle-tested;
            the config form flags it so users know to expect rough edges.
        setup_url: Optional link to a user-facing setup guide, shown in the
            config form when the service needs steps taken outside
            PrintGuard before it can connect. Falls back to docs_url.
        setup_hint: Optional one-line note rendered above the config fields
            for those same out-of-band steps.
        schema: JSON Schema describing the configuration form. Property
            extensions: "secret" marks sensitive fields, "placeholder"
            provides input hints. A standard "default" is preselected, so an
            optional choice never renders as an empty one.
    """

    id: str
    label: str
    docs_url: str
    desktop_only: bool = False
    experimental: bool = False
    setup_url: str | None = None
    setup_hint: str | None = None
    schema: dict[str, Any]

    def meta(self) -> dict[str, Any]:
        """Serialises adapter metadata for schema-driven configuration UIs."""
        return {
            "id": self.id,
            "label": self.label,
            "docs_url": self.docs_url,
            "desktop_only": self.desktop_only,
            "experimental": self.experimental,
            "setup_url": self.setup_url,
            "setup_hint": self.setup_hint,
            "schema": self.schema,
        }

    def secret_fields(self) -> dict[str, str]:
        """Config property names the schema marks secret (credentials), each with its title."""
        return {key: prop["title"] for key, prop in self.schema.get("properties", {}).items() if prop.get("secret")}

    def secret_keys(self) -> set[str]:
        """Config property names the schema marks secret (credentials)."""
        return set(self.secret_fields())

    def declared(self, config: dict[str, Any]) -> dict[str, Any]:
        """Keeps the fields of a configuration the schema declares, without the whitespace around their text.

        A field another service marks secret would otherwise linger unhidden,
        and a key pasted with a space or a line break after it is refused as a
        header by every request that carries it.

        Args:
            config: The values supplied for the schema.

        Returns:
            The configuration to check and store.
        """
        return {key: value.strip() if isinstance(value, str) else value for key, value in config.items() if key in self.schema["properties"]}

    def restored(self, config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Makes a stored configuration one a save would take, since every save sends it back whole.

        A number where the schema wants text, which an earlier version stored
        as it was sent, becomes that text.

        Args:
            config: The configuration as the state file holds it.

        Returns:
            The declared configuration without the values that still fail
            their field's type or choices, and the titles of the fields that
            lost one.
        """
        properties = self.schema["properties"]
        config = self.declared(
            {
                key: str(value) if type(value) in (int, float) and properties.get(key, {}).get("type") == "string" else value
                for key, value in config.items()
            }
        )
        reset = []
        for key in list(config):
            try:
                require_typed(config, {key: properties[key]})
            except ValueError:
                del config[key]
                reset.append(properties[key]["title"])
        return config, reset

    def require(self, config: dict[str, Any]) -> None:
        """Refuses a configuration with a value of the wrong type or outside its choices, or a field the service needs left blank.

        Args:
            config: The values supplied for the schema.

        Raises:
            ValueError: If a value is not of the type its field declares or
                not one of the choices it offers, or a field the schema marks
                required is blank, naming each.
        """
        require_typed(config, self.schema.get("properties", {}))
        blank = [
            self.schema["properties"][key]["title"]
            for key in self.schema.get("required", [])
            if not str(config.get(key) or "").strip()
        ]
        if blank:
            raise ValueError(f"{self.label} needs {' and '.join(blank)} filled in")


def redirect_message(response: httpx.Response) -> str:
    """Says where a redirect points, since an adapter never follows one.

    Args:
        response: A 3xx answer carrying a Location header.

    Returns:
        A sentence naming both addresses and what to register instead.
    """
    source, target = (f"{url.scheme}://{url.netloc.decode()}" for url in (response.url, response.url.join(response.headers["location"])))
    return f"{source} redirects to {target}. Register the address the service answers on"


def multipart_form(
    fields: dict[str, str], file_field: str, filename: str, file_bytes: bytes, content_type: str = "image/jpeg"
) -> tuple[dict[str, str], AsyncIterator[bytes]]:
    """Encodes text fields plus one file as a multipart/form-data request.

    The body is streamed with its length declared, so the file is sent from
    where it is held and never copied into a second buffer.

    Args:
        fields: Plain form fields.
        file_field: Form name of the file part.
        filename: Filename reported for the file part.
        file_bytes: Content of the file part.
        content_type: Media type reported for the file part.

    Returns:
        (headers, body) ready for the platform HTTP function.
    """
    boundary = uuid.uuid4().hex
    head = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ) + (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    async def body() -> AsyncIterator[bytes]:
        yield head
        yield file_bytes
        yield tail

    return {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(head) + len(file_bytes) + len(tail)),
    }, body()
