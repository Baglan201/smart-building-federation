"""Persistent replay protection and a small audit trail, with atomic acceptance."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ReplayDetected(Exception):
    pass


class State:
    def __init__(self, path: Path):
        self.path = path
        if not path.exists():
            path.touch(mode=0o600, exist_ok=False)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS used_nonces (
                    requester TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    PRIMARY KEY (requester, nonce)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def consume(self, requester: str, nonce: str, now: int) -> None:
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO used_nonces VALUES (?, ?, ?)", (requester, nonce, now)
                )
                connection.execute(
                    "INSERT INTO audit(timestamp, event, requester, reason) VALUES (?, ?, ?, ?)",
                    (now, "share_granted", requester, "accepted"),
                )
        except sqlite3.IntegrityError as error:
            raise ReplayDetected from error

    def record(self, now: int, event: str, requester: str, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO audit(timestamp, event, requester, reason) VALUES (?, ?, ?, ?)",
                (now, event, requester, reason),
            )
