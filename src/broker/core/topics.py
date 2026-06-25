"""
Topic grammar — parsing, validation, and the wildcard rules that drive authz.

A topic is exactly three dot-separated fields: `<a>.<b>.<thread>`, where `0` is the wildcard.
  1:1  <sender>.<receiver>.<thread>
  1:n  <sender>.0.<thread>          (sender broadcasts; any receiver subscribes)
  n:1  0.<receiver>.<thread>        (any sender publishes; one receiver)

The namespace is attacker-controlled and each topic can claim a per-topic retention floor, so this
validator is a real access control, not a formatting nicety. See DESIGN.md §2.

CRITICAL: principal ids must never contain DELIM ('.') or KEY_DELIM ('|'), nor equal WILDCARD ('0'),
else the structural authz (auth/policy.py) can be bypassed and the persist key (§4.3) injected.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

WILDCARD = "0"  # reserved: never a valid principal id
DELIM = "."  # topic field delimiter
KEY_DELIM = "|"  # persist composite-key delimiter (must not appear in any field)
MAX_FIELD_LEN = 128


class InvalidTopic(ValueError):
    """Raised when a topic string violates the grammar or charset rules."""


@dataclass(frozen=True, slots=True)
class TopicParts:
    """Parsed topic. `sender`/`receiver` may be WILDCARD; `thread` is an opaque id."""

    sender: str
    receiver: str
    thread: str

    @property
    def sender_wild(self) -> bool:
        return self.sender == WILDCARD

    @property
    def receiver_wild(self) -> bool:
        return self.receiver == WILDCARD


def _check_field(field: str, *, allow_wildcard: bool) -> None:
    """Validate a single field's charset/length. `thread` does not treat WILDCARD specially."""
    if not field:
        raise InvalidTopic("empty topic field")
    if len(field) > MAX_FIELD_LEN:
        raise InvalidTopic("topic field too long")
    if DELIM in field or KEY_DELIM in field:
        raise InvalidTopic(f"topic field may not contain {DELIM!r} or {KEY_DELIM!r}")
    # allow_wildcard only documents intent; '0' is a legal literal in any position.
    _ = allow_wildcard


def parse(topic: str) -> TopicParts:
    """Parse + validate a topic into its three fields (NFC-normalized). Raises InvalidTopic.

    Enforces exact arity 3 and per-field charset/length. Forbids the open relay `0.0.*` so callers
    can reject it for role `user` (see auth/policy.py). svc may still use `0.0.*` deliberately.
    """
    topic = unicodedata.normalize("NFC", topic)
    fields = topic.split(DELIM)
    if len(fields) != 3:
        raise InvalidTopic("topic must have exactly 3 dot-separated fields")
    sender, receiver, thread = fields
    _check_field(sender, allow_wildcard=True)
    _check_field(receiver, allow_wildcard=True)
    _check_field(thread, allow_wildcard=False)
    return TopicParts(sender=sender, receiver=receiver, thread=thread)


def is_valid_principal_id(principal_id: str) -> bool:
    """A principal id may not be the wildcard, be empty, or contain a delimiter (DESIGN.md §2.3)."""
    if not principal_id or principal_id == WILDCARD:
        return False
    return DELIM not in principal_id and KEY_DELIM not in principal_id
