"""Per-topic token-bucket rate limiter (DESIGN.md §5.3). Clock injected — no sleeps."""

from __future__ import annotations

from broker.core.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_burst_then_block() -> None:
    clk = FakeClock()
    rl = RateLimiter(capacity=10, refill_per_sec=10.0, clock=clk)
    assert all(rl.allow("a.b.t") for _ in range(10))  # 10-msg burst
    assert not rl.allow("a.b.t")  # 11th blocked


def test_refill_over_time() -> None:
    clk = FakeClock()
    rl = RateLimiter(capacity=10, refill_per_sec=10.0, clock=clk)
    for _ in range(10):
        rl.allow("a.b.t")
    assert not rl.allow("a.b.t")
    clk.t += 0.5  # 0.5s * 10/s = 5 tokens
    assert sum(rl.allow("a.b.t") for _ in range(10)) == 5


def test_per_topic_isolation() -> None:
    clk = FakeClock()
    rl = RateLimiter(capacity=2, refill_per_sec=1.0, clock=clk)
    assert rl.allow("x.y.1") and rl.allow("x.y.1") and not rl.allow("x.y.1")
    # a different topic has its own bucket
    assert rl.allow("x.y.2")


def test_lru_eviction_recreates_full() -> None:
    clk = FakeClock()
    rl = RateLimiter(capacity=1, refill_per_sec=1.0, max_topics=1, clock=clk)
    assert rl.allow("t1")  # t1 drained
    assert rl.allow("t2")  # evicts t1
    assert rl.allow("t1")  # t1 recreated full → allowed (safe behavior)
