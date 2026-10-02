"""Playground demo: a sample conversation through the real Store/Gate.

Runs fully offline with the RuleJudge stub (stated on every run: the
stub is not Jev). It admits six chat lines, prints each gate
verdict, then shows recall, inject, and the quarantine queue. The
recorded output lives in docs/playground.md.

Run: python3 playground/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from uncluttered_memory.gate import Gate, RuleJudge  # noqa: E402
from uncluttered_memory.inject import Injector  # noqa: E402
from uncluttered_memory.recall import Recall  # noqa: E402
from uncluttered_memory.store import Store, token_jaccard  # noqa: E402

LINES = [
    ("alice", "standup 9am daily", "chat"),
    ("alice", "My visa interview is on Monday at the downtown office",
     "chat"),
    ("alice", "ok", "chat"),
    ("alice", "lol that meeting was hilarious lol", "chat"),
    ("alice", "The weather was nice yesterday in some vague way", "chat"),
    ("alice", "My phone number is 555-1234, call me anytime", "chat"),
]


def main() -> int:
    print("UnclutteredMemory playground (offline RuleJudge stub, not Jev)")
    store = Store(":memory:")
    gate = Gate(RuleJudge())
    for user, text, source in LINES:
        decision = gate.decide(text, [], [])
        action = store.admit(text, source, gate, user)
        print("IN   %r" % text)
        print("GATE action=%s reasons=%s" % (decision.action,
                                             ",".join(decision.reasons)))
        print("STORE action=%s" % action)
    recall = Recall()
    query = "standup daily"
    scored = [(t, token_jaccard(query, t))
              for _, t, _ in store.live("alice")]
    texts = recall.select(sorted(scored, key=lambda kv: -kv[1]))
    print("RECALL query=%r texts=%r" % (query, texts))
    packed = Injector().pack([(t, s) for t, s in scored if t in texts])
    print("INJECT context=%r" % packed)
    quar = store.quarantined("alice")
    print("REVIEW quarantined=%d" % len(quar))
    for qid, text, reason in quar:
        print("Q qid=%d reason=%s text=%r" % (qid, reason, text))
    print("STATUS live=%d quarantined=%d error_count=%d"
          % (len(store.live("alice")), len(quar), store.error_count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
