"""
Core domain models.

Purpose: the data carried across the broker — messages, topics, subscriptions, principals,
and the (epoch, seq) cursor. Pure data; no I/O. See DESIGN.md §2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Two roles only (DESIGN.md §5)."""

    SVC = "svc"  # all access
    USER = "user"  # pub/sub on owned topics only


@dataclass(frozen=True, slots=True)
class Cursor:
    """A subscriber position.

    `epoch` is minted per process start; `seq` is per-topic monotonic. A stale epoch or a seq
    older than the earliest-retained message resolves to a 409/gap (DESIGN.md §2.1).
    """

    epoch: str
    seq: int


@dataclass(frozen=True, slots=True)
class Message:
    """A published message. `seq` is assigned inside the SQLite write transaction."""

    topic: str
    seq: int
    epoch: str
    payload: bytes
    ts: float  # epoch seconds; passed in (no wall-clock in pure helpers)
    headers: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class Watermarks:
    """Per-topic positions. `accepted` = highest seq written; `durable` = highest replicated to the
    external store (DESIGN.md §6.1). In ephemeral mode durable is undefined (None).
    """

    topic: str
    accepted: int
    durable: int | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller. Authority over a topic is derived structurally from the topic name
    (DESIGN.md §2.2), so there is no stored owned_topics set. `id` must satisfy the principal-id
    rules in core.topics (not the wildcard, no delimiters).
    """

    id: str
    role: Role


@dataclass(frozen=True, slots=True)
class Subscription:
    """A durable (webhook) subscription. Server-owned delivery state (DESIGN.md §4.1)."""

    id: str
    topic: str
    owner: str
    callback_url: str
    cursor_seq: int
    suspended: bool = False
    consecutive_failures: int = 0
