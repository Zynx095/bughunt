import base64
import hashlib

import pytest

from app.engines.crypto import merkle


def test_sha256_known_vector(run):
    r = run("crypto", "hash", {"text": "abc"})
    assert r.success
    assert r.result["digest"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert r.confidence is None  # deterministic results carry no confidence


def test_hash_requires_exactly_one_input(run):
    r = run("crypto", "hash", {})
    assert not r.success and r.error.code == "INVALID_INPUT"


def test_aes_gcm_roundtrip_and_role_gate(run):
    assert run("crypto", "generate_key", {"label": "k1", "key_type": "aes256"}).success
    enc = run("crypto", "encrypt", {"text": "patient 42", "key_label": "k1", "associated_data": "rec-1"})
    assert enc.success and enc.result["algorithm"] == "AES-256-GCM"
    payload = {"key_label": "k1", "ciphertext_b64": enc.result["ciphertext_b64"], "nonce_b64": enc.result["nonce_b64"],
               "associated_data": "rec-1"}
    denied = run("crypto", "decrypt", payload, role="analyst")
    assert not denied.success and denied.error.code == "FORBIDDEN"
    ok = run("crypto", "decrypt", payload, role="reviewer")
    assert ok.success and ok.result["text"] == "patient 42"


def test_aes_gcm_detects_tampering_and_wrong_aad(run):
    run("crypto", "generate_key", {"label": "k2", "key_type": "aes256"})
    enc = run("crypto", "encrypt", {"text": "hello", "key_label": "k2"}).result
    ct = bytearray(base64.b64decode(enc["ciphertext_b64"]))
    ct[0] ^= 1
    bad = run("crypto", "decrypt", {"key_label": "k2", "nonce_b64": enc["nonce_b64"],
                                    "ciphertext_b64": base64.b64encode(bytes(ct)).decode()}, role="reviewer")
    assert bad.error.code == "AUTHENTICATION_FAILED"
    wrong_aad = run("crypto", "decrypt", {"key_label": "k2", "nonce_b64": enc["nonce_b64"],
                                          "ciphertext_b64": enc["ciphertext_b64"], "associated_data": "x"}, role="reviewer")
    assert wrong_aad.error.code == "AUTHENTICATION_FAILED"


def test_sign_and_verify(run):
    key = run("crypto", "generate_key", {"label": "signer", "key_type": "ed25519"}).result
    assert "BEGIN PUBLIC KEY" in key["public_key_pem"]
    sig = run("crypto", "sign", {"text": "manifest", "key_label": "signer"})
    assert sig.success
    good = run("crypto", "verify", {"text": "manifest", "signature_b64": sig.result["signature_b64"], "public_key_pem": key["public_key_pem"]})
    bad = run("crypto", "verify", {"text": "manifest!", "signature_b64": sig.result["signature_b64"], "public_key_pem": key["public_key_pem"]})
    assert good.result["valid"] is True and bad.result["valid"] is False
    assert not run("crypto", "sign", {"text": "x", "key_label": "signer"}, role="viewer").success


def test_ai_actor_cannot_sign(run):
    run("crypto", "generate_key", {"label": "signer2", "key_type": "ed25519"})
    r = run("crypto", "sign", {"text": "x", "key_label": "signer2"}, role="admin", actor_type="ai")
    assert r.error.code == "FORBIDDEN"


def test_secret_material_never_listed(run, services):
    run("crypto", "generate_key", {"label": "k3", "key_type": "hmac"})
    listing = run("crypto", "list_keys", {}).result
    assert all("wrapped_material" not in k for k in listing["keys"])
    raw = services.store.find_key_by_label("k3")["wrapped_material"]
    assert len(base64.b64decode(raw)) == 12 + 32 + 16  # nonce + key + GCM tag: stored wrapped, not raw


def test_hmac_is_keyed_and_stable(run):
    run("crypto", "generate_key", {"label": "p", "key_type": "hmac"})
    a = run("crypto", "hmac", {"text": "MRN-1", "key_label": "p"}).result["hmac_sha256"]
    b = run("crypto", "hmac", {"text": "MRN-1", "key_label": "p"}).result["hmac_sha256"]
    assert a == b and a != hashlib.sha256(b"MRN-1").hexdigest()


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 13])
def test_merkle_proofs_verify_for_every_leaf(n):
    leaves = [f"item-{i}".encode() for i in range(n)]
    root = merkle.root(leaves).hex()
    for i in range(n):
        assert merkle.verify(leaves[i], merkle.proof(leaves, i), root)
        assert not merkle.verify(b"tampered", merkle.proof(leaves, i), root)


def test_merkle_domain_separation():
    # A two-leaf root must not equal the leaf hash of the concatenated leaf hashes (second-preimage guard).
    a, b = b"a", b"b"
    root = merkle.root([a, b])
    assert root != merkle.leaf_hash(merkle.leaf_hash(a) + merkle.leaf_hash(b))


def test_merkle_engine_ops(run):
    digests = [hashlib.sha256(x.encode()).hexdigest() for x in "abc"]
    res = run("crypto", "merkle_root", {"leaves": digests, "leaf_encoding": "sha256_hex", "include_proofs": True}).result
    ok = run("crypto", "merkle_verify", {"leaf": digests[1], "leaf_encoding": "sha256_hex", "proof": res["proofs"][1], "root": res["root"]})
    assert ok.result["valid"] is True
