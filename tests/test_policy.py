"""Structural authz — svc=all, user gated by topic sender/receiver fields (DESIGN.md §2.2)."""

from __future__ import annotations

import pytest

from broker.auth.policy import Action, Forbidden, authorize
from broker.core.models import Principal, Role
from broker.core.topics import parse


def _p(role: Role, pid: str = "alice") -> Principal:
    return Principal(id=pid, role=role)


# --- svc: unconditional ---
def test_svc_any_action_any_topic() -> None:
    authorize(_p(Role.SVC), parse("0.0.t"), Action.PUBLISH)  # even open relay
    authorize(_p(Role.SVC), parse("x.y.t"), Action.SUBSCRIBE)


# --- 1:1 ---
def test_user_publishes_as_sender() -> None:
    authorize(_p(Role.USER, "alice"), parse("alice.bob.t"), Action.PUBLISH)


def test_user_cannot_publish_as_other_sender() -> None:
    with pytest.raises(Forbidden):
        authorize(_p(Role.USER, "alice"), parse("bob.alice.t"), Action.PUBLISH)


def test_user_subscribes_as_receiver() -> None:
    authorize(_p(Role.USER, "bob"), parse("alice.bob.t"), Action.SUBSCRIBE)


def test_user_cannot_subscribe_as_other_receiver() -> None:
    with pytest.raises(Forbidden):
        authorize(_p(Role.USER, "bob"), parse("alice.carol.t"), Action.SUBSCRIBE)


# --- wildcards ---
def test_user_any_sender_publishes_to_fan_in() -> None:
    # n:1  0.bob.t  → any sender may publish
    authorize(_p(Role.USER, "alice"), parse("0.bob.t"), Action.PUBLISH)


def test_user_any_receiver_subscribes_to_broadcast() -> None:
    # 1:n  alice.0.t → any receiver may subscribe
    authorize(_p(Role.USER, "carol"), parse("alice.0.t"), Action.SUBSCRIBE)


def test_user_open_relay_forbidden() -> None:
    with pytest.raises(Forbidden):
        authorize(_p(Role.USER, "alice"), parse("0.0.t"), Action.PUBLISH)
