"""Recall and rerank never crash on unseen or paraphrased queries.

P1 read-path hardening only: no golden label or threshold changes here.
Twenty novel paraphrases (hand-written for this test, disjoint from both
eval sets) run through the full offline read path. Each must return
without raising, with a sane output shape: a list of stored texts within
cap, and a pack string within budget.
"""
import json
import pathlib

from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store
from uncluttered_memory import thresholds as th

REPO = pathlib.Path(__file__).resolve().parents[1]

# Twenty novel paraphrases of ordinary standing facts. Written for this
# test only; none appears in the golden or bulk eval sets (pinned below).
PARAPHRASES = [
    "the corner bakery opens its doors at seven in the morning",
    "the corner bakery starts serving customers at 7am",
    "our weekly planning session moved to Thursday afternoon",
    "the Thursday afternoon slot now holds the planning session",
    "the lab centrifuge sits on the third floor bench",
    "you will find the lab centrifuge benchtop upstairs on floor three",
    "the ferry to the island leaves the harbor at half past six",
    "the island ferry departs the harbor at 6:30",
    "the office ficus needs watering every third day",
    "water the office ficus plant once every three days",
    "the night bus route was extended past the old depot",
    "the late bus now runs beyond the former depot stop",
    "the archive key hangs on a hook behind the front desk",
    "behind the front desk a hook holds the archive key",
    "the dentist appointment falls on the second Tuesday of March",
    "March second Tuesday is when the dentist visit lands",
    "the shared printer only accepts recycled paper trays",
    "load the shared printer with recycled paper only",
    "the rooftop beehive honey harvest happens each September",
    "each September brings the rooftop beehive honey harvest",
]


def _overlap_score(query, text):
    q = set(query.lower().split())
    t = set(text.lower().split())
    if not q or not t:
        return 0.0
    return len(q & t) / len(q | t)


def _eval_texts():
    texts = set()
    for name in ("eval/golden.jsonl", "eval/frozen.jsonl"):
        path = REPO / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except ValueError:
                continue
            if isinstance(case, dict) and case.get("text"):
                texts.add(" ".join(str(case["text"]).split()).lower())
    return texts


def test_paraphrases_are_novel_to_eval_sets():
    corpus = _eval_texts()
    assert corpus, "eval text corpus unexpectedly empty"
    for p in PARAPHRASES:
        norm = " ".join(p.split()).lower()
        assert norm not in corpus, "paraphrase leaks into eval sets: %r" % p


def test_recall_never_crashes_on_unseen_paraphrases():
    assert len(PARAPHRASES) == 20
    store = Store()
    seeds = [
        "the corner bakery opens at seven in the morning",
        "planning session is on Thursdays",
        "the lab centrifuge is upstairs",
        "the island ferry leaves at half past six",
        "water the office ficus regularly",
    ]
    for s in seeds:
        store.put(s, "user")
    live = [t for _, t, *_ in store.live()]
    assert live, "seed store unexpectedly empty"
    gate = Gate(RuleJudge())
    recall = Recall()
    for q in PARAPHRASES:
        decision = gate.decide(q)
        assert decision.action in ("STORE", "DROP", "QUARANTINE")
        assert isinstance(decision.reasons, list)
        scored = [(t, _overlap_score(q, t)) for t in live]
        out = recall.select(scored)
        assert isinstance(out, list)
        assert len(out) <= th.RECALL_CAP
        assert set(out) <= set(live)
        scores = dict(scored)
        assert out == sorted(out, key=lambda t: -scores[t])
        packed = recall.pack(out)
        assert isinstance(packed, str)
        assert len(packed) <= th.RECALL_PACK_BUDGET_CHARS


def test_recall_edge_inputs_keep_shape():
    recall = Recall()
    assert recall.select([]) == []
    assert recall.select([("", 0.99)]) == [""]
    assert recall.select([("snow" * 5000, 0.95)]) == ["snow" * 5000]
    assert recall.pack([]) == ""
    assert isinstance(recall.pack(["caf\u00e9 \u2615 \u8bb0\u5f55"]), str)
