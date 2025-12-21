from fastapi import Request, HTTPException, Depends, Response
from fastapi.routing import APIRoute
from typing import Callable
from ..core.config import get_settings
from ..core.crypto import CryptoHandler
import base64
import json
import logging

_GLOBAL_HANDLER = None
_LOGGER = logging.getLogger(__name__)

def _get_header(scope_headers: list[tuple[bytes, bytes]], name: str) -> str | None:
    """Read a header from ASGI scope headers without instantiating Request.headers (avoid caching)."""
    key = name.lower().encode("latin-1")
    for k, v in scope_headers:
        if k.lower() == key:
            return v.decode("latin-1")
    return None

def get_crypto_handler():
    global _GLOBAL_HANDLER
    if _GLOBAL_HANDLER is not None:
        return _GLOBAL_HANDLER
    settings = get_settings()
    if settings.crypto_private_key:
        try:
            private_key_bytes = base64.b64decode(settings.crypto_private_key)
            _GLOBAL_HANDLER = CryptoHandler(private_key_bytes)
        except Exception:
            _GLOBAL_HANDLER = CryptoHandler()
    else:
        _GLOBAL_HANDLER = CryptoHandler()
    return _GLOBAL_HANDLER

class EncryptedRoute(APIRoute):
    
    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()
        
        async def custom_handler(request: Request) -> Response:
            handler = get_crypto_handler()
            scope_headers = request.scope.get("headers", [])
            is_encrypted = (_get_header(scope_headers, "x-encrypted") == "true")
            client_pub_key = _get_header(scope_headers, "x-client-public-key")
            if is_encrypted:
                if not handler:
                    raise HTTPException(status_code=500, detail="Server crypto not configured")
                if not client_pub_key:
                    raise HTTPException(status_code=400, detail="Missing X-Client-Public-Key header")
                try:
                    body = await request.body()
                    if body:
                        client_public_key_bytes = base64.b64decode(client_pub_key)
                        shared_key = handler.derive_shared_key(client_public_key_bytes)
                        decrypted_body = handler.decrypt(body, shared_key)
                        request._body = decrypted_body
                        new_headers = []
                        for k, v in request.scope["headers"]:
                            if k.lower() not in (b"content-type", b"content-length"):
                                new_headers.append((k, v))
                        new_headers.append((b"content-type", b"application/json"))
                        new_headers.append((b"content-length", str(len(decrypted_body)).encode("ascii")))
                        request.scope["headers"] = new_headers
                        if hasattr(request, "_headers"):
                            request._headers = None
                        async def receive():
                            return {
                                "type": "http.request",
                                "body": decrypted_body,
                                "more_body": False,
                            }
                        request._receive = receive
                        _LOGGER.debug(f"Decrypted request body: {decrypted_body.decode('utf-8')}")
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Decryption failed: {str(e)}")
            response: Response = await original_handler(request)
            if is_encrypted and handler and client_pub_key:
                try:
                    body_bytes = response.body
                    if not body_bytes and hasattr(response, "render"):
                        body_bytes = response.render(response.content)
                    client_public_key_bytes = base64.b64decode(client_pub_key)
                    shared_key = handler.derive_shared_key(client_public_key_bytes)
                    encrypted_res = handler.encrypt(body_bytes, shared_key)
                    passthrough_headers = {
                        k: v
                        for k, v in dict(response.headers).items()
                        if k.lower() not in ("content-length", "content-type")
                    }
                    return Response(
                        content=encrypted_res,
                        status_code=response.status_code,
                        headers={
                            **passthrough_headers,
                            "X-Encrypted": "true",
                            "Content-Type": "application/octet-stream"
                        }
                    )
                except Exception as e:
                    _LOGGER.error(f"Response encryption failed: {e}")
                    if response.status_code < 400:
                        raise HTTPException(status_code=500, detail=f"Encryption failed: {str(e)}")
            return response

        return custom_handler

def encrypt_response(data: dict, client_public_key_b64: str, handler: CryptoHandler) -> str:
    if not handler or not client_public_key_b64:
        return json.dumps(data)
    client_public_key_bytes = base64.b64decode(client_public_key_b64)
    shared_key = handler.derive_shared_key(client_public_key_bytes)
    return handler.encrypt_b64(json.dumps(data), shared_key)

async def decrypt_request(request: Request, handler: CryptoHandler = Depends(get_crypto_handler)):
    if request.headers.get("X-Encrypted") != "true":
        return await request.json()
    client_public_key_b64 = request.headers.get("X-Client-Public-Key")
    if not client_public_key_b64:
        raise HTTPException(status_code=400, detail="Missing X-Client-Public-Key header")
    try:
        client_public_key_bytes = base64.b64decode(client_public_key_b64)
        shared_key = handler.derive_shared_key(client_public_key_bytes)
        body = await request.body()
        decrypted_body = handler.decrypt(body, shared_key)
        return json.loads(decrypted_body.decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Decryption failed: {str(e)}")
