"""Offline trusted commissioning. Never exposed as an HTTP registration route."""

import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from building_federation.crypto import digest, encode, encrypt, private_bytes, public_text, split

NODES = ("hvac", "lighting", "access")
ROLES = {
    "hvac": {"zone": "floor-1", "target_temperature_c": 22},
    "lighting": {"zone": "floor-2", "night_brightness_percent": 20},
    "access": {"zone": "main-entrance", "allowed_groups": ["staff", "maintenance"]},
}


def write_private(path: Path, content: bytes) -> None:
    """Create a private file without an initial world-readable window (POSIX)."""
    with open(path, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
        file.write(content)


def provision(root: Path, base_port: int = 8101) -> None:
    if not 1024 <= base_port <= 65533:
        raise ValueError("Base port must be between 1024 and 65533")
    # Refuse any existing destination: no silent key rotation or data destruction.
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    keys = {node: Ed25519PrivateKey.generate() for node in NODES}
    records = {}
    held_shares: dict[str, dict[str, str]] = {node: {} for node in NODES}
    for index, node in enumerate(NODES):
        directory = root / node
        directory.mkdir(mode=0o700)
        write_private(directory / "identity.pem", private_bytes(keys[node]))
        manifest = f"controller={node}\nfirmware=simulation-1.0\nsite=building-alpha\n".encode()
        write_private(directory / "manifest.txt", manifest)
        storage_key = secrets.token_bytes(32)
        encrypted = encrypt(storage_key, {"controller": node, "settings": ROLES[node]}, node)
        write_private(directory / "storage.enc", encrypted)
        holders = [peer for peer in NODES if peer != node]
        for holder, share in zip(holders, split(storage_key), strict=True):
            held_shares[holder][node] = encode(share)
        records[node] = {
            "url": f"http://127.0.0.1:{base_port + index}",
            "public_key": public_text(keys[node]),
            "manifest_sha256": digest(manifest),
            "ciphertext_sha256": digest(encrypted),
            "holders": holders,
        }
    for node in NODES:
        config = {"node_id": node, "members": records, "held_shares": held_shares[node]}
        write_private(root / node / "config.json", json.dumps(config, indent=2).encode())
