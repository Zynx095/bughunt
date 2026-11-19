"""Key management.

`KeyManager` is the interface; `LocalKeyStore` is the foundation implementation:
secret key material is wrapped (AES-256-GCM) under a key-encryption key (KEK)
and stored in SQLite. The KEK comes from OMNIFORGE_MASTER_KEY or, for local
development only, a generated key file. Swap in a KMS/HSM-backed KeyManager
for production without changing the crypto engine.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_TYPES = ("aes256", "ed25519", "hmac")


class KeyManager(Protocol):
    def create(self, label: str, key_type: str) -> dict[str, Any]: ...
    def ensure(self, label: str, key_type: str) -> dict[str, Any]: ...
    def secret(self, key_id: str) -> tuple[dict[str, Any], bytes]: ...
    def list(self) -> list[dict[str, Any]]: ...
    def resolve(self, key_id: str | None, label: str | None) -> dict[str, Any] | None: ...


def load_kek(master_key_b64: str | None, data_dir: Path) -> tuple[bytes, str]:
    if master_key_b64:
        kek = base64.b64decode(master_key_b64)
        if len(kek) != 32:
            raise ValueError("OMNIFORGE_MASTER_KEY must be base64 of exactly 32 bytes")
        return kek, "environment"
    path = data_dir / "master.key"
    if path.exists():
        return base64.b64decode(path.read_text().strip()), "dev_key_file"
    data_dir.mkdir(parents=True, exist_ok=True)
    kek = AESGCM.generate_key(bit_length=256)
    path.write_text(base64.b64encode(kek).decode())
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - best effort on Windows
        pass
    return kek, "dev_key_file"


class LocalKeyStore:
    def __init__(self, store, kek: bytes, kek_source: str) -> None:
        self.store = store
        self._kek = AESGCM(kek)
        self.kek_source = kek_source

    def _wrap(self, material: bytes, aad: bytes) -> str:
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self._kek.encrypt(nonce, material, aad)).decode()

    def _unwrap(self, wrapped: str, aad: bytes) -> bytes:
        raw = base64.b64decode(wrapped)
        return self._kek.decrypt(raw[:12], raw[12:], aad)

    def create(self, label: str, key_type: str) -> dict[str, Any]:
        if key_type not in KEY_TYPES:
            raise ValueError(f"Unsupported key type '{key_type}'")
        public_pem = None
        if key_type == "ed25519":
            priv = Ed25519PrivateKey.generate()
            material = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                          serialization.NoEncryption())
            public_pem = priv.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        else:
            material = os.urandom(32)
        aad = f"{label}|{key_type}".encode()
        row = self.store.add_key(label=label, key_type=key_type, public_key_pem=public_pem,
                                 wrapped_material=self._wrap(material, aad))
        row.pop("wrapped_material", None)
        return row

    def ensure(self, label: str, key_type: str) -> dict[str, Any]:
        existing = self.store.find_key_by_label(label)
        if existing and existing["key_type"] == key_type:
            existing.pop("wrapped_material", None)
            return existing
        return self.create(label, key_type)

    def resolve(self, key_id: str | None, label: str | None) -> dict[str, Any] | None:
        if key_id:
            return self.store.get_key(key_id)
        if label:
            return self.store.find_key_by_label(label)
        return None

    def secret(self, key_id: str) -> tuple[dict[str, Any], bytes]:
        row = self.store.get_key(key_id)
        if row is None:
            raise KeyError(key_id)
        material = self._unwrap(row["wrapped_material"], f"{row['label']}|{row['key_type']}".encode())
        row.pop("wrapped_material", None)
        return row, material

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_keys()
