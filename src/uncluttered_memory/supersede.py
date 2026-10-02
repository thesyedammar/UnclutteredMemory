"""Supersede lifecycle: code orders pairs, judges vote relation, code tombstones.

Judges only cast the relation vote. Code owns ordering, agreement,
tombstones, and rollback. Destructive acts need two agreeing judges.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RELATIONS = ("same", "contradict", "supersede", "unrelated")
DESTRUCTIVE = ("same", "contradict", "supersede")


class RelationJudge:
    """Judge protocol. Real Jev wiring comes later."""

    def relation(self, old_text: str, new_text: str) -> str:
        raise NotImplementedError("wire Jev-System-One here")


class FakeRelationJudge(RelationJudge):
    """Deterministic stub for tests and offline runs."""

    def __init__(self, votes: dict):
        self.votes = votes

    def relation(self, old_text, new_text):
        return self.votes[(old_text, new_text)]


@dataclass
class SupersedeDecision:
    relation: str
    agreed: bool
    action: str  # TOMBSTONE or KEEP
    reasons: list = field(default_factory=list)


def candidate_pairs(facts: list) -> list:
    """Code-ordered pairs. facts: [(id, text), ...]. Oldest id first.

    Emits every (older, newer) pair with older id < newer id, sorted
    by (older id, newer id). The judge never orders dates.
    """
    ordered = sorted(facts, key=lambda f: f[0])
    pairs = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            pairs.append((ordered[i], ordered[j]))
    return pairs


def decide(old_text: str, new_text: str, judge_a: RelationJudge,
           judge_b: RelationJudge) -> SupersedeDecision:
    va = judge_a.relation(old_text, new_text)
    vb = judge_b.relation(old_text, new_text)
    if va not in RELATIONS or vb not in RELATIONS:
        return SupersedeDecision("unrelated", False, "KEEP", ["invalid-label-veto"])
    if va != vb:
        return SupersedeDecision(va, False, "KEEP", ["disagree-veto"])
    if va == "unrelated":
        return SupersedeDecision(va, True, "KEEP", ["unrelated-agreed"])
    return SupersedeDecision(va, True, "TOMBSTONE", [va + "-agreed"])


def apply(store, old_id: int, new_id: int, decision: SupersedeDecision,
          actor: str = "code", reason: str = "") -> bool:
    """Apply an agreed destructive decision as a soft tombstone. No-op on veto."""
    if decision.action != "TOMBSTONE" or not decision.agreed:
        return False
    store.tombstone(old_id, new_id, reason or decision.relation, actor)
    return True


def human_override(store, fact_id: int, action: str, actor: str = "human",
                   target_id=None, reason: str = "") -> None:
    """Named-human rollback or force. action: restore | retire | tombstone."""
    if action == "restore":
        store.restore(fact_id)
    elif action in ("retire", "tombstone"):
        if target_id is None:
            raise ValueError("target_id required to retire a fact")
        store.tombstone(fact_id, target_id, reason or ("human-" + action), actor)
    else:
        raise ValueError("action must be restore, retire, or tombstone")
