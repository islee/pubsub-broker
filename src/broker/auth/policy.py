"""
Authz policy — structural, derived from the topic name (DESIGN.md §2.2).

Authority is a pure function of (principal, parsed topic, action) — there is no stored ownership.
For role `user`:
  - publish   permitted iff topic.sender   == principal.id OR topic.sender   == WILDCARD
  - subscribe permitted iff topic.receiver == principal.id OR topic.receiver == WILDCARD
`svc` is always permitted. `0.0.*` (open relay) is forbidden for `user`.
"""

from __future__ import annotations

from enum import StrEnum

from ..core.models import Principal, Role
from ..core.topics import TopicParts


class Action(StrEnum):
    PUBLISH = "publish"
    SUBSCRIBE = "subscribe"


class Forbidden(Exception):
    """Raised when a principal may not perform an action on a topic (transport maps to 403)."""


def authorize(principal: Principal, topic: TopicParts, action: Action) -> None:
    """Enforce the structural policy. Raise Forbidden otherwise.

    NOTE: validation of the topic string (arity, charset, reserved ids) happens in core.topics.parse
    before this; this function assumes a parsed, well-formed topic.
    """
    if principal.role is Role.SVC:
        return

    # user role: the open relay 0.0.* is svc-only.
    if topic.sender_wild and topic.receiver_wild:
        raise Forbidden("0.0.* (open relay) is reserved for svc")

    if action is Action.PUBLISH:
        if topic.sender_wild or topic.sender == principal.id:
            return
        raise Forbidden(f"{principal.id} may not publish to sender={topic.sender!r}")

    if action is Action.SUBSCRIBE:
        if topic.receiver_wild or topic.receiver == principal.id:
            return
        raise Forbidden(f"{principal.id} may not subscribe to receiver={topic.receiver!r}")

    raise Forbidden(f"unknown action {action!r}")
