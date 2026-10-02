"""RateLimiter.check retry_after comes from the true oldest entry.

Round-3 finding: the backoff read only the first entry of each
recorded list (`self._calls[:1]` plus `self._chars[:1]`). That happens
to work for append-ordered histories, but it is a heuristic, not the
contract: the retry hint must be the time until the true oldest entry
still inside the window leaves it, whatever order the histories are
in. These tests craft exact call histories with an injected clock and
pin the exact backoff seconds.
"""
from uncluttered_memory.server import RateLimiter


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def test_call_cap_retry_after_pins_exact_backoff():
    clock = FakeClock(100.0)
    rl = RateLimiter(calls_per_min=2, chars_per_min=10 ** 9,
                     window_secs=60, clock=clock)
    assert rl.check(0) == (True, 0)
    clock.t = 110.0
    assert rl.check(0) == (True, 0)
    clock.t = 115.0
    ok, retry = rl.check(0)
    # oldest call (t=100) leaves the window at t=160; from 115 that is
    # 45 seconds, and the hint rounds up by one.
    assert ok is False
    assert retry == 46


def test_retry_after_reads_true_oldest_not_first_list_entry():
    """A crafted history where the first entry is not the oldest."""
    clock = FakeClock(150.0)
    rl = RateLimiter(calls_per_min=10 ** 9, chars_per_min=10,
                     window_secs=60, clock=clock)
    # Out-of-order char history: the true oldest is t=100 (6 chars),
    # not the first list entry (t=130, 4 chars).
    rl._chars = [(130.0, 4), (100.0, 6)]
    ok, retry = rl.check(1)
    assert ok is False
    # oldest (t=100) leaves at 160; from 150 that is 10 seconds + 1.
    assert retry == 11


def test_retry_after_reads_true_oldest_across_both_histories():
    clock = FakeClock(140.0)
    rl = RateLimiter(calls_per_min=1, chars_per_min=10,
                     window_secs=60, clock=clock)
    # One call at t=120, a char charge at t=100: the true oldest is
    # the char entry, so the hint must use t=100 (leaves at 160).
    rl._calls = [120.0]
    rl._chars = [(100.0, 10)]
    ok, retry = rl.check(1)
    assert ok is False
    assert retry == 21


def test_empty_window_reports_the_full_window():
    """No entries at all (one request over the whole char budget)."""
    clock = FakeClock(500.0)
    rl = RateLimiter(calls_per_min=10 ** 9, chars_per_min=10,
                     window_secs=60, clock=clock)
    ok, retry = rl.check(999)
    assert ok is False
    assert retry == 61


def test_pruned_entries_do_not_count_toward_the_backoff():
    clock = FakeClock(200.0)
    rl = RateLimiter(calls_per_min=10 ** 9, chars_per_min=10,
                     window_secs=60, clock=clock)
    rl._chars = [(100.0, 10), (150.0, 4)]
    ok, retry = rl.check(7)
    assert ok is False
    # t=100 is older than the window (cutoff 140): pruned before the
    # hint is computed, so the oldest live entry is t=150 (leaves at
    # 210; from 200 that is 10 seconds + 1).
    assert retry == 11


def test_refused_check_consumes_nothing():
    clock = FakeClock(10.0)
    rl = RateLimiter(calls_per_min=1, chars_per_min=10 ** 9,
                     window_secs=60, clock=clock)
    assert rl.check(0) == (True, 0)
    assert rl.check(0)[0] is False
    clock.t = 11.0
    assert rl.check(0)[0] is False
    assert len(rl._calls) == 1  # refusals never append


def test_retry_after_through_http_body():
    """The 429 body carries the same pinned hint."""
    from uncluttered_memory.gate import RuleJudge
    from uncluttered_memory.server import MemoryApp
    from uncluttered_memory.store import Store

    clock = FakeClock(100.0)
    rl = RateLimiter(calls_per_min=1, chars_per_min=10 ** 9,
                     window_secs=60, clock=clock)
    app = MemoryApp(Store(":memory:"), RuleJudge(), limiter=rl)
    assert app.handle("status", {"user": "u"})[0] == 200
    clock.t = 115.0
    status, body = app.handle("status", {"user": "u"})
    assert status == 429
    assert body["retry_after_secs"] == 46
