"""Cryptography engine — standard primitives from `cryptography` and `hashlib` only.

Operations: hashing, HMAC (keyed pseudonymisation), AES-256-GCM encryption,
Ed25519 signatures, Merkle roots/proofs and stored-file integrity checks.
Private/secret key material never leaves the key manager.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, model_validator

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation

from . import merkle
from .keystore import KEY_TYPES, KeyManager

HASHES = {"sha256": hashlib.sha256, "sha3_256": hashlib.sha3_256, "sha512": hashlib.sha512, "blake2b": hashlib.blake2b}
MAX_BYTES = 20 * 1024 * 1024


def _decode_b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EngineError("INVALID_BASE64", f"'{field}' is not valid base64") from exc


class DataInput(BaseModel):
    text: str | None = Field(None, description="UTF-8 text input")
    data_b64: str | None = Field(None, description="Binary input as base64")

    @model_validator(mode="after")
    def _one_source(self):
        if (self.text is None) == (self.data_b64 is None):
            raise ValueError("Provide exactly one of 'text' or 'data_b64'")
        return self

    def raw(self) -> bytes:
        data = self.text.encode("utf-8") if self.text is not None else _decode_b64(self.data_b64 or "", "data_b64")
        if len(data) > MAX_BYTES:
            raise EngineError("PAYLOAD_TOO_LARGE", "Input exceeds 20 MB", 413)
        return data


class HashInput(DataInput):
    algorithm: Literal["sha256", "sha3_256", "sha512", "blake2b"] = "sha256"


class KeyRef(BaseModel):
    key_id: str | None = None
    key_label: str | None = Field(None, max_length=128)


class HmacInput(DataInput, KeyRef):
    pass


class GenerateKeyInput(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)
    key_type: Literal["aes256", "ed25519", "hmac"] = "aes256"
    reuse_existing: bool = Field(True, description="Return the existing key with this label/type if present")


class EncryptInput(DataInput, KeyRef):
    associated_data: str | None = Field(None, max_length=1024, description="Authenticated (not encrypted) context, e.g. a record id")


class DecryptInput(KeyRef):
    ciphertext_b64: str
    nonce_b64: str
    associated_data: str | None = Field(None, max_length=1024)


class SignInput(DataInput, KeyRef):
    pass


class VerifyInput(DataInput):
    signature_b64: str
    public_key_pem: str | None = None
    key_id: str | None = None


class MerkleInput(BaseModel):
    leaves: list[str] = Field(..., min_length=1, max_length=100_000)
    leaf_encoding: Literal["text", "sha256_hex"] = "text"
    include_proofs: bool = False


class MerkleVerifyInput(BaseModel):
    leaf: str
    leaf_encoding: Literal["text", "sha256_hex"] = "text"
    proof: list[dict[str, str]]
    root: str = Field(..., min_length=64, max_length=64)


class DocumentRef(BaseModel):
    document_id: str


class EmptyInput(BaseModel):
    pass


def _leaf_bytes(value: str, encoding: str) -> bytes:
    if encoding == "sha256_hex":
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise EngineError("INVALID_HEX", f"Leaf is not valid hex: {value[:16]}...") from exc
        if len(raw) != 32:
            raise EngineError("INVALID_HEX", "sha256_hex leaves must be 32-byte digests")
        return raw
    return value.encode("utf-8")


class CryptoEngine(BaseEngine):
    name = "crypto"
    title = "Cryptography Engine"
    description = "SHA-2/3 hashing, HMAC, AES-256-GCM, Ed25519 signatures, Merkle proofs, file integrity, key management."

    def __init__(self, keys: KeyManager, store=None, kek_source: str = "unknown") -> None:
        super().__init__()
        self.keys = keys
        self.store = store
        self.kek_source = kek_source

    def health(self) -> dict:
        h = super().health()
        h["kek_source"] = self.kek_source
        if self.kek_source == "dev_key_file":
            h["warning"] = "Using a locally generated development master key; set OMNIFORGE_MASTER_KEY for real use."
        return h

    def _key(self, ref: KeyRef, expected: str) -> tuple[dict, bytes]:
        row = self.keys.resolve(ref.key_id, ref.key_label)
        if row is None:
            raise EngineError("KEY_NOT_FOUND", "Key not found; generate one with crypto.generate_key", 404)
        meta, secret = self.keys.secret(row["id"])
        if meta["key_type"] != expected:
            raise EngineError("WRONG_KEY_TYPE", f"Key '{meta['label']}' is {meta['key_type']}, expected {expected}")
        return meta, secret

    @operation("hash", HashInput, description="Hash text or bytes (SHA-256 default)")
    def op_hash(self, data: HashInput, ctx: ExecutionContext) -> OpResult:
        raw = data.raw()
        return OpResult(result={"algorithm": data.algorithm, "digest": HASHES[data.algorithm](raw).hexdigest(),
                                "bytes": len(raw)})

    @operation("hmac", HmacInput, description="HMAC-SHA256 with a managed key (e.g. keyed pseudonymisation of identifiers)")
    def op_hmac(self, data: HmacInput, ctx: ExecutionContext) -> OpResult:
        meta, secret = self._key(data, "hmac")
        mac = hmac.new(secret, data.raw(), hashlib.sha256).hexdigest()
        return OpResult(result={"hmac_sha256": mac, "key_id": meta["id"], "key_label": meta["label"]})

    @operation("generate_key", GenerateKeyInput, access="write", description="Create (or reuse) a managed key; secret material is never returned")
    def op_generate_key(self, data: GenerateKeyInput, ctx: ExecutionContext) -> OpResult:
        if data.key_type not in KEY_TYPES:
            raise EngineError("UNSUPPORTED_KEY_TYPE", data.key_type)
        row = self.keys.ensure(data.label, data.key_type) if data.reuse_existing else self.keys.create(data.label, data.key_type)
        if self.store is not None:
            self.store.audit("crypto", "key_available", actor=ctx.actor, role=ctx.role,
                             detail={"key_id": row["id"], "label": row["label"], "type": row["key_type"]})
        return OpResult(result={k: row[k] for k in ("id", "label", "key_type", "public_key_pem", "created_at")})

    @operation("list_keys", EmptyInput, description="List key metadata (never secret material)")
    def op_list_keys(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result={"keys": self.keys.list(), "kek_source": self.kek_source})

    @operation("encrypt", EncryptInput, access="write", description="AES-256-GCM authenticated encryption with a managed key")
    def op_encrypt(self, data: EncryptInput, ctx: ExecutionContext) -> OpResult:
        meta, secret = self._key(data, "aes256")
        nonce = os.urandom(12)
        aad = data.associated_data.encode() if data.associated_data else None
        ct = AESGCM(secret).encrypt(nonce, data.raw(), aad)
        return OpResult(result={"algorithm": "AES-256-GCM", "key_id": meta["id"], "key_label": meta["label"],
                                "nonce_b64": base64.b64encode(nonce).decode(), "ciphertext_b64": base64.b64encode(ct).decode(),
                                "associated_data": data.associated_data})

    @operation("decrypt", DecryptInput, access="sensitive", permission="crypto:decrypt",
               description="Decrypt AES-256-GCM ciphertext (requires crypto:decrypt)")
    def op_decrypt(self, data: DecryptInput, ctx: ExecutionContext) -> OpResult:
        meta, secret = self._key(data, "aes256")
        aad = data.associated_data.encode() if data.associated_data else None
        try:
            pt = AESGCM(secret).decrypt(_decode_b64(data.nonce_b64, "nonce_b64"), _decode_b64(data.ciphertext_b64, "ciphertext_b64"), aad)
        except InvalidTag as exc:
            raise EngineError("AUTHENTICATION_FAILED", "Ciphertext, nonce, key or associated data do not match (tampered or wrong key)") from exc
        if self.store is not None:
            self.store.audit("crypto", "decrypt", actor=ctx.actor, role=ctx.role, severity="notice",
                             detail={"key_id": meta["id"], "associated_data": data.associated_data})
        try:
            return OpResult(result={"text": pt.decode("utf-8"), "key_id": meta["id"]})
        except UnicodeDecodeError:
            return OpResult(result={"data_b64": base64.b64encode(pt).decode(), "key_id": meta["id"]})

    @operation("sign", SignInput, access="sensitive", permission="crypto:sign",
               description="Ed25519 signature with a managed key (requires crypto:sign)")
    def op_sign(self, data: SignInput, ctx: ExecutionContext) -> OpResult:
        meta, secret = self._key(data, "ed25519")
        priv = Ed25519PrivateKey.from_private_bytes(secret)
        sig = priv.sign(data.raw())
        if self.store is not None:
            self.store.audit("crypto", "sign", actor=ctx.actor, role=ctx.role, severity="notice",
                             detail={"key_id": meta["id"], "message_sha256": hashlib.sha256(data.raw()).hexdigest()})
        return OpResult(result={"algorithm": "Ed25519", "signature_b64": base64.b64encode(sig).decode(),
                                "key_id": meta["id"], "public_key_pem": meta["public_key_pem"]})

    @operation("verify", VerifyInput, description="Verify an Ed25519 signature against a public key or managed key id")
    def op_verify(self, data: VerifyInput, ctx: ExecutionContext) -> OpResult:
        pem = data.public_key_pem
        if not pem and data.key_id:
            row = self.keys.resolve(data.key_id, None)
            pem = row and row.get("public_key_pem")
        if not pem:
            raise EngineError("PUBLIC_KEY_REQUIRED", "Provide public_key_pem or the key_id of an ed25519 key")
        try:
            pub = serialization.load_pem_public_key(pem.encode())
        except ValueError as exc:
            raise EngineError("INVALID_PUBLIC_KEY", "Could not parse public key PEM") from exc
        if not isinstance(pub, Ed25519PublicKey):
            raise EngineError("INVALID_PUBLIC_KEY", "Only Ed25519 public keys are supported")
        try:
            pub.verify(_decode_b64(data.signature_b64, "signature_b64"), data.raw())
            valid = True
        except InvalidSignature:
            valid = False
        return OpResult(result={"valid": valid, "algorithm": "Ed25519"})

    @operation("merkle_root", MerkleInput, description="Merkle root (RFC 6962-style) over ordered leaves, optionally with inclusion proofs")
    def op_merkle_root(self, data: MerkleInput, ctx: ExecutionContext) -> OpResult:
        leaves = [_leaf_bytes(v, data.leaf_encoding) for v in data.leaves]
        levels = merkle.build_levels(leaves)
        result = {"root": levels[-1][0].hex(), "leaf_count": len(leaves), "height": len(levels) - 1,
                  "leaf_hashes": [h.hex() for h in levels[0]]}
        if data.include_proofs:
            if len(leaves) > 2000:
                raise EngineError("TOO_MANY_PROOFS", "include_proofs supports at most 2000 leaves")
            result["proofs"] = [merkle.proof(leaves, i) for i in range(len(leaves))]
        return OpResult(result=result, metadata={"scheme": "SHA-256, 0x00 leaf / 0x01 node prefixes, odd node promoted"})

    @operation("merkle_verify", MerkleVerifyInput, description="Verify a Merkle inclusion proof")
    def op_merkle_verify(self, data: MerkleVerifyInput, ctx: ExecutionContext) -> OpResult:
        try:
            ok = merkle.verify(_leaf_bytes(data.leaf, data.leaf_encoding), data.proof, data.root)
        except (KeyError, ValueError) as exc:
            raise EngineError("INVALID_PROOF", f"Malformed proof: {exc}") from exc
        return OpResult(result={"valid": ok})

    @operation("verify_document", DocumentRef, description="Recompute a stored file's SHA-256 and compare with the hash recorded at upload")
    def op_verify_document(self, data: DocumentRef, ctx: ExecutionContext) -> OpResult:
        if self.store is None:
            raise EngineError("NO_STORE", "Document storage is not configured", 503)
        doc = self.store.get_document(data.document_id)
        if doc is None:
            raise EngineError("DOCUMENT_NOT_FOUND", "Unknown document id", 404)
        path = Path(doc["storage_path"])
        if not path.exists():
            raise EngineError("FILE_MISSING", "Stored file is missing", 410)
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        current = h.hexdigest()
        intact = hmac.compare_digest(current, doc["sha256"])
        if not intact and self.store is not None:
            self.store.audit("security", "integrity_violation", actor=ctx.actor, role=ctx.role, severity="critical",
                             detail={"document_id": doc["id"], "recorded": doc["sha256"], "current": current})
        return OpResult(result={"document_id": doc["id"], "filename": doc["filename"], "recorded_sha256": doc["sha256"],
                                "current_sha256": current, "intact": intact})
