"""Strict wire types; signed bodies contain no floating point values."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeId = Literal["hvac", "lighting", "access"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class UnlockRequest(StrictModel):
    protocol: Literal["building-federation/v1"] = "building-federation/v1"
    action: Literal["release-share"] = "release-share"
    requester: NodeId
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    issued_at: int
    expires_at: int
    manifest_sha256: Digest
    ciphertext_sha256: Digest


class SignedRequest(StrictModel):
    body: UnlockRequest
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class ShareGrant(StrictModel):
    protocol: Literal["building-federation/v1"] = "building-federation/v1"
    action: Literal["share-granted"] = "share-granted"
    holder: NodeId
    requester: NodeId
    request_sha256: Digest
    share: Annotated[str, Field(min_length=44, max_length=44)]


class SignedGrant(StrictModel):
    body: ShareGrant
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class UnlockResult(StrictModel):
    status: Literal["unlocked"] = "unlocked"
    node_id: NodeId
    approved_by: list[NodeId]
    data: dict


class HealthResult(StrictModel):
    node_id: NodeId
    status: Literal["ready"] = "ready"
    policy: Literal["both-other-peers"] = "both-other-peers"


class EmptyBody(StrictModel):
    pass
