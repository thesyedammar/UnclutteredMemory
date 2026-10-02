"""Write-path gate: one batched judgment call, enforcement in code.

The judge answers three typed questions per line. Code owns every
decision after that: drop / quarantine / store. No meaning in the ifs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateVote:
    durable: float  # 0..1 durable-or-chatter
    importance: int  # 1..5
    stop: float  # 0..1 stop-or-pass (high = block)
    play: float = 0.0  # 0..1 playful/joke signal
    sensitive: float = 0.0  # 0..1 private-data signal


@dataclass
class GateDecision:
    action: str  # STORE, QUARANTINE, DROP
    reasons: list = field(default_factory=list)


class JudgeClient:
    """Real Jev HTTP client goes here. Tests inject FakeJudge."""

    def vote(self, text: str, neighbors: list, facts: list) -> GateVote:
        raise NotImplementedError("wire Jev-System-One here (jev-1.13)")


class FakeJudge(JudgeClient):
    """Deterministic stub for tests and offline runs."""

    def __init__(self, votes: dict):
        self.votes = votes

    def vote(self, text, neighbors, facts):
        return self.votes[text]


PLAY_DROP = 0.7
SENSITIVE_DROP = 0.7


class Gate:
    def __init__(self, judge: JudgeClient):
        self.judge = judge

    def decide(self, text: str, neighbors=None, facts=None, importance_min: int = 3) -> GateDecision:
        v = self.judge.vote(text, neighbors or [], facts or [])
        if v.play > PLAY_DROP:
            return GateDecision("DROP", ["play>0.7"])
        if v.sensitive > SENSITIVE_DROP:
            return GateDecision("DROP", ["sensitive>0.7"])
        if v.stop >= 0.58:
            return GateDecision("QUARANTINE", ["stop>=0.58"])
        if v.durable >= 0.58 and v.importance >= importance_min:
            return GateDecision("STORE", ["durable+important"])
        return GateDecision("DROP", ["not-durable-or-trivial"])
