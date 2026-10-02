"""Supersede lifecycle: code orders pairs, judges vote relation, code applies.

Judges only cast the relation vote. Code owns ordering, agreement,
application, and rollback. A soft tombstone is applied only when both
judges agree the new text supersedes the old one.

Offline, the two judges are heterogeneous by construction: the eval and
the tests pair StrictRelationJudge with LenientRelationJudge (see
jev_client.offline_relation_pair), two distinct heuristics that
genuinely disagree on crafted near-misses, so agreement is evidence
rather than a tautology.

An agreed clash never tombstones: the pair is marked
conflict_unresolved (both facts stay live, both carry the counterpart
mark, and the pair lands in the conflicts table for a human). Coexist
and unrelated also keep both facts live. These labels are the ones the
native Jev relation question asks for, plus legacy aliases.

Labels accepted: supersede | coexist | conflict_unresolved | unrelated |
same (legacy alias: contradict maps to conflict_unresolved).
"""
from __future__ import annotations

from dataclasses import dataclass, field

RELATIONS = ("same", "contradict", "conflict_unresolved",
             "supersede", "coexist", "unrelated")

#: Relations that may soft-tombstone the older fact, and only with
#: two agreeing judges.
TOMBSTONE_RELATIONS = ("supersede",)

#: Clash relations: both facts stay live, both are marked with the
#: counterpart, never tombstoned.
CONFLICT_RELATIONS = ("contradict", "conflict_unresolved")

BENIGN_RELATIONS = ("same", "coexist", "unrelated")


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
    action: str  # TOMBSTONE, CONFLICT, or KEEP
    reasons: list = field(default_factory=list)


def canonical_relation(label: str) -> str:
    """Map the legacy contradict label onto the design vocabulary."""
    if label == "contradict":
        return "conflict_unresolved"
    return label


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
    """Paired relation vote. Destructive apply needs both judges agreeing.

    - supersede agreed: soft tombstone the old fact (new supersedes it).
    - clash agreed (contradict / conflict_unresolved): mark both
      conflict_unresolved and keep both live. Never tombstone.
    - coexist / unrelated / same agreed: keep both live.
    - disagreement or an unknown label: veto, keep everything.
    """
    va = judge_a.relation(old_text, new_text)
    vb = judge_b.relation(old_text, new_text)
    if va not in RELATIONS or vb not in RELATIONS:
        return SupersedeDecision("unrelated", False, "KEEP",
                                 ["invalid-label-veto"])
    if va != vb:
        return SupersedeDecision(va, False, "KEEP", ["disagree-veto"])
    rel = canonical_relation(va)
    if rel in TOMBSTONE_RELATIONS:
        return SupersedeDecision(rel, True, "TOMBSTONE", [rel + "-agreed"])
    if rel in CONFLICT_RELATIONS:
        return SupersedeDecision(rel, True, "CONFLICT",
                                 ["conflict-unresolved-never-tombstone"])
    return SupersedeDecision(rel, True, "KEEP", [rel + "-agreed"])


def apply(store, old_id: int, new_id: int, decision: SupersedeDecision,
          actor: str = "code", reason: str = "") -> bool:
    """Apply an agreed decision. No-op (False) on veto.

    TOMBSTONE soft-tombstones the old fact. CONFLICT marks both facts
    conflict_unresolved, keeps both live, and records the pair.
    """
    if not decision.agreed:
        return False
    if decision.action == "TOMBSTONE":
        store.tombstone(old_id, new_id, reason or decision.relation, actor)
        return True
    if decision.action == "CONFLICT":
        store.mark_conflict(old_id, new_id, reason or decision.relation,
                            actor)
        return True
    return False


def human_override(store, fact_id: int, action: str, actor: str = "human",
                   target_id=None, reason: str = "") -> None:
    """Named-human override. Every action is documented and tested:

    - restore: clear the tombstone fields on fact_id; it goes live
      again (target_id and reason are ignored).
    - retire: soft-tombstone fact_id toward target_id (required); the
      stored reason defaults to "human-retire".
    - tombstone: explicit alias of retire, the same soft tombstone
      toward target_id (required), default reason "human-tombstone".

    The stored tombstone_actor is `actor` for both destructive
    actions. Any other action raises ValueError, and retire/tombstone
    without target_id raise ValueError.
    """
    if action == "restore":
        store.restore(fact_id)
    elif action in ("retire", "tombstone"):
        if target_id is None:
            raise ValueError("target_id required to retire a fact")
        store.tombstone(fact_id, target_id, reason or ("human-" + action), actor)
    else:
        raise ValueError("action must be restore, retire, or tombstone")
