"""Peer policy and unlocking, independent of FastAPI and the command line."""

import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidSignature, InvalidTag

from building_federation.crypto import (
    canonical,
    combine,
    decode,
    decrypt,
    digest,
    load_private,
    public_text,
    sign,
    verify,
)
from building_federation.models import (
    ShareGrant,
    SignedGrant,
    SignedRequest,
    UnlockRequest,
    UnlockResult,
)
from building_federation.settings import Settings
from building_federation.state import ReplayDetected, State

REQUEST_TTL = 30
CLOCK_SKEW = 5


class Rejected(Exception):
    def __init__(self, code: str, status: int = 403):
        self.code = code
        self.status = status
        super().__init__(code)


class Node:
    def __init__(
        self,
        directory: Path,
        client: httpx.Client,
        clock: Callable[[], float] = time.time,
    ):
        self.directory = directory
        self.settings = Settings.load(directory)
        self.node_id = self.settings.node_id
        self.key = load_private((directory / "identity.pem").read_bytes())
        if public_text(self.key) != self.settings.members[self.node_id].public_key:
            raise ValueError("Local private key does not match pinned identity")
        for share in self.settings.held_shares.values():
            if len(decode(share)) != 32:
                raise ValueError("Invalid provisioned share length")
        self.state = State(directory / "state.sqlite3")
        self.client = client
        self.clock = clock
        self._unlock_lock = threading.Lock()

    def make_request(self) -> SignedRequest:
        now = int(self.clock())
        body = UnlockRequest(
            requester=self.node_id,
            nonce=secrets.token_hex(32),
            issued_at=now,
            expires_at=now + REQUEST_TTL,
            manifest_sha256=digest((self.directory / "manifest.txt").read_bytes()),
            ciphertext_sha256=digest((self.directory / "storage.enc").read_bytes()),
        )
        return SignedRequest(body=body, signature=sign(self.key, body.model_dump()))

    def _validate_request(self, request: SignedRequest) -> None:
        body = request.body
        record = self.settings.members[body.requester]
        if body.requester == self.node_id:
            raise Rejected("self_approval_forbidden")
        try:
            verify(record.public_key, body.model_dump(), request.signature)
        except (InvalidSignature, ValueError) as error:
            raise Rejected("invalid_request_signature") from error
        now = int(self.clock())
        if (
            body.issued_at > now + CLOCK_SKEW
            or body.expires_at <= now
            or not 0 < body.expires_at - body.issued_at <= REQUEST_TTL
        ):
            raise Rejected("request_not_fresh")
        if body.manifest_sha256 != record.manifest_sha256:
            raise Rejected("manifest_mismatch")
        if body.ciphertext_sha256 != record.ciphertext_sha256:
            raise Rejected("ciphertext_mismatch")

    def grant_share(self, request: SignedRequest) -> SignedGrant:
        now = int(self.clock())
        try:
            self._validate_request(request)
            body = ShareGrant(
                holder=self.node_id,
                requester=request.body.requester,
                request_sha256=digest(canonical(request.body.model_dump())),
                share=self.settings.held_shares[request.body.requester],
            )
            result = SignedGrant(body=body, signature=sign(self.key, body.model_dump()))
            try:
                self.state.consume(request.body.requester, request.body.nonce, now)
            except ReplayDetected as error:
                raise Rejected("replay_detected", 409) from error
            return result
        except Rejected as error:
            self.state.record(now, "share_denied", request.body.requester, error.code)
            raise

    def validate_grant(self, grant: SignedGrant, request: SignedRequest, holder: str) -> bytes:
        body = grant.body
        if (
            body.holder != holder
            or body.requester != self.node_id
            or body.request_sha256 != digest(canonical(request.body.model_dump()))
        ):
            raise Rejected("grant_binding_mismatch")
        try:
            verify(self.settings.members[holder].public_key, body.model_dump(), grant.signature)
            share = decode(body.share)
            if len(share) != 32:
                raise ValueError("Invalid share length")
        except (InvalidSignature, ValueError) as error:
            raise Rejected("invalid_grant_signature_or_share") from error
        return share

    def unlock(self) -> UnlockResult:
        # Avoid parallel local demos interleaving their audit trails.
        with self._unlock_lock:
            return self._unlock()

    def _unlock(self) -> UnlockResult:
        request = self.make_request()
        encrypted = (self.directory / "storage.enc").read_bytes()
        # Check the same bytes that will later be decrypted, closing a file-change race.
        if digest(encrypted) != request.body.ciphertext_sha256:
            raise Rejected("storage_changed_during_request")
        holders = self.settings.members[self.node_id].holders
        shares: dict[str, bytes] = {}
        for holder in holders:
            try:
                response = self.client.post(
                    f"{self.settings.members[holder].url}/v1/share",
                    json=request.model_dump(),
                )
                response.raise_for_status()
                grant = SignedGrant.model_validate(response.json())
                shares[holder] = self.validate_grant(grant, request, holder)
            except (httpx.HTTPError, ValueError, Rejected):
                # Do not record response bodies: they contain secret shares.
                self.state.record(int(self.clock()), "peer_rejected", self.node_id, holder)
        if set(shares) != set(holders):
            self.state.record(
                int(self.clock()), "unlock_denied", self.node_id, "quorum_unavailable"
            )
            raise Rejected("quorum_unavailable", 503)
        if int(self.clock()) >= request.body.expires_at:
            raise Rejected("request_expired_during_collection")
        key = combine(shares[holders[0]], shares[holders[1]])
        try:
            data = decrypt(key, encrypted, self.node_id)
        except (InvalidTag, ValueError, KeyError) as error:
            self.state.record(
                int(self.clock()), "unlock_denied", self.node_id, "storage_auth_failed"
            )
            raise Rejected("storage_auth_failed") from error
        self.state.record(
            int(self.clock()), "unlock_succeeded", self.node_id, "both_peers_verified"
        )
        # No persistent unlocked flag, full key file, or plaintext output file.
        return UnlockResult(node_id=self.node_id, approved_by=holders, data=data)
