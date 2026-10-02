"""Write-path gate: one batched judgment call, enforcement in code.

The judge answers typed questions per line. Code owns every
decision after that: drop / quarantine / store. No meaning in the ifs.
Unseen or low-confidence input fails closed to quarantine, never an
exception. RuleJudge is an offline heuristic stub, not Jev.

Every decision cutoff is a parameter of Gate.decide whose default
lives in thresholds.py; no numeric decision boundary is hardcoded in
this module's logic paths. The reason strings echo the effective
cutoff so an override is visible in the decision record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import thresholds as th


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


# Word-ish laugh tokens only: "lollipop" must not read as play.
LAUGH_RE = re.compile(r"(?<![a-z])(?:lol|lmao|rofl|(?:ha){2,})(?![a-z])")
FILLER = {"ok", "k", "fine", "sure", "yes", "no", "hey", "hi", "hello",
          "thanks", "thx", "cool", "nice", "yo", "okay", "okey", "kk",
          "got it", "sounds good", "will do"}
CONTACT = ("number", "phone", "mobile", "ssn", "otp", "card", "account",
           "address", "email", "passcode", "password")
DURABLE_MARK = ("prefer", "standup", "deadline", "allerg", "stop-loss",
                "stoploss", "limit", "always", "never", "%")

# RuleJudge vote levels: heuristic stub outputs, not decision cutoffs.
# The cutoffs that read these live in thresholds.py.
FILLER_LEVELS = (0.05, 1, 0.1)
FILLER_CONF = 0.9
PLAY_LEVELS = (0.3, 1, 0.2)
PLAY_SIGNAL = 0.85
PLAY_CONF = 0.8
SENSITIVE_LEVELS = (0.6, 2, 0.1)
SENSITIVE_SIGNAL = 0.9
SENSITIVE_CONF = 0.8
DURABLE_DURABLE = 0.9
DURABLE_STOP = 0.05
DURABLE_CONF = 0.8
DURABLE_HARD_IMPORTANCE = 5
DURABLE_SOFT_IMPORTANCE = 4
UNCERTAIN_LEVELS = (0.5, 2, 0.4)
UNCERTAIN_CONF = 0.2
HARD_MARKS = ("%", "stop-loss", "deadline", "allerg", "limit")


def _laugh(low: str) -> bool:
    return LAUGH_RE.search(low) is not None


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
            return GateVote(*FILLER_LEVELS, conf=FILLER_CONF)
        if _laugh(low) or _identity_claim(t, low):
            return GateVote(*PLAY_LEVELS, play=PLAY_SIGNAL, conf=PLAY_CONF)
        if _sensitive(low):
            return GateVote(*SENSITIVE_LEVELS, sensitive=SENSITIVE_SIGNAL,
                            conf=SENSITIVE_CONF)
        if _durable(low):
            imp = (DURABLE_HARD_IMPORTANCE
                   if any(w in low for w in HARD_MARKS)
                   else DURABLE_SOFT_IMPORTANCE)
            return GateVote(DURABLE_DURABLE, imp, DURABLE_STOP,
                            conf=DURABLE_CONF)
        return GateVote(*UNCERTAIN_LEVELS, conf=UNCERTAIN_CONF)


def _num(v: float) -> str:
    """Compact threshold rendering for reasons: 0.7 -> '0.7'."""
    return "%g" % v


class Gate:
    def __init__(self, judge: JudgeClient):
        self.judge = judge

    def decide(self, text: str, neighbors=None, facts=None,
               importance_min: int = th.IMPORTANCE_MIN,
               durable_min: float = th.DURABLE_MIN,
               stop_block: float = th.STOP_BLOCK,
               min_conf: float = th.MIN_CONF,
               play_drop: float = th.PLAY_DROP,
               sensitive_drop: float = th.SENSITIVE_DROP) -> GateDecision:
        v = self.judge.vote(text, neighbors or [], facts or [])
        if v.conf < min_conf:
            return GateDecision("QUARANTINE", ["uncertain-low-conf"])
        if v.play > play_drop:
            return GateDecision("DROP", ["play>" + _num(play_drop)])
        if v.sensitive > sensitive_drop:
            return GateDecision("DROP", ["sensitive>" + _num(sensitive_drop)])
        if v.stop >= stop_block:
            return GateDecision("QUARANTINE",
                                ["stop>=" + _num(stop_block)])
        if v.durable >= durable_min and v.importance >= importance_min:
            return GateDecision("STORE", ["durable+important"])
        return GateDecision("DROP", ["not-durable-or-trivial"])
