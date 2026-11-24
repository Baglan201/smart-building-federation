"""Library cryptography and a deliberately simple 2-of-2 XOR key split."""

import base64
import hashlib
import json
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def canonical(value: dict) -> bytes:
    """A protocol-local JSON encoding, shared by every signer and verifier."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def private_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_text(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )


def load_private(value: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(value, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Expected an Ed25519 private key")
    return key


def sign(key: Ed25519PrivateKey, body: dict) -> str:
    return encode(key.sign(canonical(body)))


def verify(public_pem: str, body: dict, signature: str) -> None:
    key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Expected an Ed25519 public key")
    key.verify(decode(signature), canonical(body))


def combine(first: bytes, second: bytes) -> bytes:
    if len(first) != 32 or len(second) != 32:
        raise ValueError("Each key share must contain 32 bytes")
    return bytes(a ^ b for a, b in zip(first, second, strict=True))


def split(key: bytes) -> tuple[bytes, bytes]:
    first = secrets.token_bytes(32)
    return first, combine(first, key)


def encrypt(key: bytes, plaintext: dict, owner: str) -> bytes:
    nonce = secrets.token_bytes(12)
    aad = canonical({"owner": owner, "format": "building-storage/v1"})
    ciphertext = AESGCM(key).encrypt(nonce, canonical(plaintext), aad)
    return canonical({"nonce": encode(nonce), "ciphertext": encode(ciphertext)})


def decrypt(key: bytes, encrypted: bytes, owner: str) -> dict:
    envelope = json.loads(encrypted)
    aad = canonical({"owner": owner, "format": "building-storage/v1"})
    plaintext = AESGCM(key).decrypt(decode(envelope["nonce"]), decode(envelope["ciphertext"]), aad)
    result = json.loads(plaintext)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result
