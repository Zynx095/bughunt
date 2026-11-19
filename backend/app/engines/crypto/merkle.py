"""Merkle tree with RFC 6962-style domain separation.

leaf = SHA256(0x00 || data), node = SHA256(0x01 || left || right).
Domain separation prevents leaf/node second-preimage confusion; an odd node at
the end of a level is promoted unchanged (no duplication, avoiding the
CVE-2012-2459 class of ambiguity).
"""
from __future__ import annotations

import hashlib

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def build_levels(leaves: list[bytes]) -> list[list[bytes]]:
    if not leaves:
        raise ValueError("Merkle tree needs at least one leaf")
    levels = [[leaf_hash(x) for x in leaves]]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = [node_hash(cur[i], cur[i + 1]) for i in range(0, len(cur) - 1, 2)]
        if len(cur) % 2:
            nxt.append(cur[-1])
        levels.append(nxt)
    return levels


def root(leaves: list[bytes]) -> bytes:
    return build_levels(leaves)[-1][0]


def proof(leaves: list[bytes], index: int) -> list[dict[str, str]]:
    levels = build_levels(leaves)
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    path: list[dict[str, str]] = []
    for level in levels[:-1]:
        if index % 2 == 1:
            path.append({"position": "left", "hash": level[index - 1].hex()})
        elif index + 1 < len(level):
            path.append({"position": "right", "hash": level[index + 1].hex()})
        index //= 2
    return path


def verify(leaf_data: bytes, path: list[dict[str, str]], expected_root_hex: str) -> bool:
    h = leaf_hash(leaf_data)
    for step in path:
        sibling = bytes.fromhex(step["hash"])
        h = node_hash(sibling, h) if step["position"] == "left" else node_hash(h, sibling)
    return h.hex() == expected_root_hex.lower()
