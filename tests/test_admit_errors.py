"""Store.admit error handling (round-3 finding): a blanket
except Exception used to hide every failure as a quarantine, so coding
bugs vanished silently.

Only judge-halt exceptions quarantine: the JevError family (rate
limit, bad key, transport failure, malformed judge answer) means the
judge could not vote. A coding bug increments the explicit error_count,
emits one structured log line (time, op, input hash, error type), and
propagates. It is never swallowed.
"""
import json
import logging

import pytest

from uncluttered_memory.gate import FakeJudge, Gate, GateVote, JudgeClient
from uncluttered_memory.jev_client import JevError, RateLimited
from uncluttered_memory.store import Store, content_hash


class HaltingJudge(JudgeClient):
    """Judge halt: the free window rate-limited mid-vote."""

    def vote(self, text, neighbors, facts):
        raise RateLimited("quota")


class TransportJudge(JudgeClient):
    """Judge halt: transport/protocol failure, not a coding bug."""

    def vote(self, text, neighbors, facts):
        raise JevError("could not reach Jev")


class BuggyJudge(JudgeClient):
    """Coding bug: a KeyError inside the judge, not a judge halt."""

    def vote(self, text, neighbors, facts):
        raise KeyError("typo in a lookup table")


def _error_records(caplog):
    return [r for r in caplog.records
            if r.name == "uncluttered_memory.store"
            and r.levelno == logging.ERROR]


def test_judge_halt_quarantines_and_does_not_count_as_error():
    s = Store()
    action = s.admit("the sky is blue", "agent", Gate(HaltingJudge()))
    assert action == "QUARANTINE"
    assert s.quarantined() == [(1, "the sky is blue", "judge-halted")]
    assert s.live() == []
    assert s.error_count == 0


def test_transport_halt_quarantines_and_does_not_count_as_error():
    s = Store()
    action = s.admit("the sky is blue", "agent", Gate(TransportJudge()))
    assert action == "QUARANTINE"
    assert s.quarantined() == [(1, "the sky is blue", "judge-halted")]
    assert s.live() == []
    assert s.error_count == 0


def test_coding_bug_propagates_counted_and_logged(caplog):
    s = Store()
    with caplog.at_level(logging.ERROR, logger="uncluttered_memory.store"):
        with pytest.raises(KeyError):
            s.admit("bug me", "agent", Gate(BuggyJudge()))
    assert s.error_count == 1
    assert s.live() == [] and s.quarantined() == []
    records = _error_records(caplog)
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["op"] == "admit"
    assert payload["input_hash"] == content_hash("bug me")
    assert payload["error_type"] == "KeyError"
    assert isinstance(payload["time"], float) and payload["time"] > 0


def test_coding_bug_counter_increments_per_occurrence(caplog):
    s = Store()
    with caplog.at_level(logging.ERROR, logger="uncluttered_memory.store"):
        for _ in range(3):
            with pytest.raises(KeyError):
                s.admit("bug me", "agent", Gate(BuggyJudge()))
    assert s.error_count == 3
    assert len(_error_records(caplog)) == 3


def _store_vote(text: str) -> Gate:
    return Gate(FakeJudge({text: GateVote(0.9, 5, 0.0)}))


def _quarantine_vote(text: str) -> Gate:
    return Gate(FakeJudge({text: GateVote(0.9, 5, 0.95)}))


def test_put_failure_counts_logs_put_op_and_propagates(caplog):
    s = Store()
    text = "a durable fact worth keeping"
    def _boom(text, source, user="local"):
        raise RuntimeError("disk is gone")
    s.put = _boom
    with caplog.at_level(logging.ERROR, logger="uncluttered_memory.store"):
        with pytest.raises(RuntimeError):
            s.admit(text, "agent", _store_vote(text))
    assert s.error_count == 1
    assert s.live() == [] and s.quarantined() == []
    records = _error_records(caplog)
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["op"] == "admit.put"
    assert payload["input_hash"] == content_hash(text)
    assert payload["error_type"] == "RuntimeError"
    assert isinstance(payload["time"], float) and payload["time"] > 0


def test_quarantine_failure_counts_logs_quarantine_op_and_propagates(
        caplog):
    s = Store()
    text = "stop me please"
    def _boom(text, reason, source="", user="local"):
        raise RuntimeError("quarantine table locked")
    s.quarantine = _boom
    with caplog.at_level(logging.ERROR, logger="uncluttered_memory.store"):
        with pytest.raises(RuntimeError):
            s.admit(text, "agent", _quarantine_vote(text))
    assert s.error_count == 1
    records = _error_records(caplog)
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["op"] == "admit.quarantine"
    assert payload["input_hash"] == content_hash(text)
    assert payload["error_type"] == "RuntimeError"
    assert isinstance(payload["time"], float) and payload["time"] > 0


def test_judge_halted_quarantine_write_failure_counts_and_propagates(
        caplog):
    s = Store()
    text = "the sky is blue"
    def _boom(text, reason, source="", user="local"):
        raise RuntimeError("quarantine table locked")
    s.quarantine = _boom
    with caplog.at_level(logging.ERROR, logger="uncluttered_memory.store"):
        with pytest.raises(RuntimeError):
            s.admit(text, "agent", Gate(HaltingJudge()))
    assert s.error_count == 1
    records = _error_records(caplog)
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["op"] == "admit.quarantine"
    assert payload["input_hash"] == content_hash(text)
    assert payload["error_type"] == "RuntimeError"
