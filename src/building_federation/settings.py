"""Validate offline trust configuration before serving any requests."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator

from building_federation.models import Digest, NodeId, StrictModel
from building_federation.provision import NODES


class Member(StrictModel):
    url: str
    public_key: str
    manifest_sha256: Digest
    ciphertext_sha256: Digest
    holders: list[NodeId]

    @field_validator("url")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.port is None
            or not 1024 <= url.port <= 65535
            or url.path
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("This simulation accepts only http://127.0.0.1:PORT peers")
        return value


class Settings(StrictModel):
    node_id: NodeId
    members: dict[NodeId, Member]
    held_shares: dict[NodeId, str]

    @model_validator(mode="after")
    def check_topology(self) -> "Settings":
        if set(self.members) != set(NODES):
            raise ValueError("Exactly three pinned members are required")
        if len({member.url for member in self.members.values()}) != 3:
            raise ValueError("Members must use distinct addresses")
        for node, member in self.members.items():
            if len(member.holders) != 2 or set(member.holders) != set(NODES) - {node}:
                raise ValueError("Each node needs the two distinct other peers")
        if set(self.held_shares) != set(NODES) - {self.node_id}:
            raise ValueError("A node stores shares only for its two peers")
        return self

    @classmethod
    def load(cls, directory: Path) -> "Settings":
        return cls.model_validate_json((directory / "config.json").read_bytes())
