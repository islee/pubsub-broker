"""Topic grammar parsing/validation (DESIGN.md §2)."""

from __future__ import annotations

import pytest

from broker.core.topics import InvalidTopic, is_valid_principal_id, parse


def test_parses_three_fields() -> None:
    t = parse("alice.bob.thread7")
    assert (t.sender, t.receiver, t.thread) == ("alice", "bob", "thread7")
    assert not t.sender_wild and not t.receiver_wild


def test_wildcard_flags() -> None:
    assert parse("alice.0.t").receiver_wild
    assert parse("0.bob.t").sender_wild


@pytest.mark.parametrize("bad", ["a.b", "a.b.c.d", "a..t", ".b.t", "a.b.", "ab", "a.b.c|d"])
def test_rejects_malformed(bad: str) -> None:
    with pytest.raises(InvalidTopic):
        parse(bad)


def test_rejects_overlong_field() -> None:
    with pytest.raises(InvalidTopic):
        parse(f"{'x' * 200}.bob.t")


def test_principal_id_rules() -> None:
    assert is_valid_principal_id("alice")
    assert not is_valid_principal_id("0")  # reserved wildcard
    assert not is_valid_principal_id("")
    assert not is_valid_principal_id("a.b")  # delimiter
    assert not is_valid_principal_id("a|b")  # key delimiter
