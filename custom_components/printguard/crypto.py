"""Cryptographic utilities for PrintGuard communication."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class CryptoHandler:
    """Handle X25519 key exchange and AES-GCM encryption."""

    def __init__(self, private_key_bytes: bytes | None = None) -> None:
        """Initialize with existing or new key pair."""
        if private_key_bytes:
            self.private_key = x25519.X25519PrivateKey.from_private_bytes(
                private_key_bytes
            )
        else:
            self.private_key = x25519.X25519PrivateKey.generate()

        self.public_key = self.private_key.public_key()

    def get_public_key_bytes(self) -> bytes:
        """Get raw public key bytes."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def get_public_key_b64(self) -> str:
        """Get base64-encoded public key."""
        return base64.b64encode(self.get_public_key_bytes()).decode("utf-8")

    def get_private_key_bytes(self) -> bytes:
        """Get raw private key bytes."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def derive_shared_key(self, peer_public_key_bytes: bytes) -> bytes:
        """Derive shared secret from peer's public key using HKDF."""
        peer_public_key = x25519.X25519PublicKey.from_public_bytes(
            peer_public_key_bytes
        )
        shared_secret = self.private_key.exchange(peer_public_key)

        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"printguard-encryption",
        ).derive(shared_secret)

    def encrypt(self, data: bytes, shared_key: bytes) -> bytes:
        """Encrypt data using AES-GCM with random nonce."""
        aesgcm = AESGCM(shared_key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    def decrypt(self, encrypted_data: bytes, shared_key: bytes) -> bytes:
        """Decrypt AES-GCM encrypted data (nonce prepended)."""
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        aesgcm = AESGCM(shared_key)
        return aesgcm.decrypt(nonce, ciphertext, None)
