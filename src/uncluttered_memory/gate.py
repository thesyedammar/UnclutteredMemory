"""Write-path gate: one batched judgment call, enforcement in code.

The judge answers typed questions per line. Code owns every
decision after that: drop / quarantine / store. No meaning in the ifs.
Unseen or low-confidence input fails closed to quarantine, never an
exception. RuleJudge is an offline heuristic stub, not Jev.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class GateVote:
    durable: float  # 0..1 durable-or-chatter
    importance: int  # 1..5
    stop: float  # 0..1 stop-or-pass (high = block)
    play: float = 0.0  # 0..1 playful/joke signal
    sensitive: float = 0.0  # 0..1 private-data signal
    conf: float = 1.0  # 0..1 judge confidence; low means abstain


@dataclass
class GateDecision:
    action: str  # STORE, QUARANTINE, DROP
    reasons: list = field(default_factory=list)


class JudgeClient:
    """Judge protocol. The base fails closed; real judges override vote()."""

    def vote(self, text: str, neighbors: list, facts: list) -> GateVote:
        return GateVote(0.5, 2, 0.5, conf=0.0)


class FakeJudge(JudgeClient):
    """Deterministic stub for branch tests. Missing keys fail closed."""

    def __init__(self, votes: dict):
        self.votes = votes

    def vote(self, text, neighbors, facts):
        v = self.votes.get(text)
        if v is None:
            return GateVote(0.5, 2, 0.5, conf=0.0)
        return v


LAUGH = ("lol", "lmao", "haha", "rofl")
FILLER = {"ok", "k", "fine", "sure", "yes", "no", "hey", "hi", "hello",
          "thanks", "thx", "cool", "nice", "yo"}
CONTACT = ("number", "phone", "mobile", "ssn", "otp", "card", "account",
           "address", "email", "passcode")
DURABLE_MARK = ("prefer", "standup", "deadline", "allerg", "stop-loss",
                "stoploss", "limit", "always", "never", "%")


def _laugh(low: str) -> bool:
    return re.search(r"lol|lmao|haha|rofl", low) is not None


def _identity_claim(raw: str, low: str) -> bool:
    """Proper-noun 'I am X' with no durable markers reads as play."""
    if re.fullmatch(r"i am ([a-z][a-z ]{0,20})", low) is None:
        return False
    if re.search(r"\d", raw) is not None:
        return False
    ent = raw.strip()[4:].strip()
    return bool(ent) and ent[0].isupper()


def _sensitive(low: str) -> bool:
    if "xxx" in low or "****" in low:
        return True
    if re.search(r"\b\d{6,}\b", low) is not None:
        return True
    return any(w in low for w in CONTACT) and re.search(r"\d", low) is not None


def _durable(low: str) -> bool:
    if "%" in low or re.search(r"\d", low) is not None:
        return True
    return any(w in low for w in DURABLE_MARK)


class RuleJudge(JudgeClient):
    """Offline heuristic keyed by text features, never by exact strings.

    Not Jev and never labeled as Jev. Anything it cannot read fails
    closed to a low-confidence vote, which the gate quarantines.
    """

    def vote(self, text, neighbors=None, facts=None):
        t = " ".join(text.split())
        low = t.lower()
        if low in FILLER or len(t) <= 2:
            return GateVote(0.05, 1, 0.1, conf=0.9)
        if _laugh(low) or _identity_claim(t, low):
            return GateVote(0.3, 1, 0.2, play=0.85, conf=0.8)
        if _sensitive(low):
            return GateVote(0.6, 2, 0.1, sensitive=0.9, conf=0.8)
        if _durable(low):
            hard = ("%", "stop-loss", "deadline", "allerg", "limit")
            imp = 5 if any(w in low for w in hard) else 4
            return GateVote(0.9, imp, 0.05, conf=0.8)
        return GateVote(0.5, 2, 0.4, conf=0.2)


PLAY_DROP = 0.7
SENSITIVE_DROP = 0.7
MIN_CONF = 0.6


class Gate:
    def __init__(self, judge: JudgeClient):
        self.judge = judge

    def decide(self, text: str, neighbors=None, facts=None,
               importance_min: int = 3, durable_min: float = 0.58) -> GateDecision:
        v = self.judge.vote(text, neighbors or [], facts or [])
        if v.conf < MIN_CONF:
            return GateDecision("QUARANTINE", ["uncertain-low-conf"])
        if v.play > PLAY_DROP:
            return GateDecision("DROP", ["play>0.7"])
        if v.sensitive > SENSITIVE_DROP:
            return GateDecision("DROP", ["sensitive>0.7"])
        if v.stop >= 0.58:
            return GateDecision("QUARANTINE", ["stop>=0.58"])
        if v.durable >= durable_min and v.importance >= importance_min:
            return GateDecision("STORE", ["durable+important"])
        return GateDecision("DROP", ["not-durable-or-trivial"])
