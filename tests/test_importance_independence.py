"""Provenance independence for the golden importance suite.

Earlier this suite mirrored the stub buckets (every 5 carried a hard
marker, 4/1/2 sat in stub buckets), so the hand-authored claim was
overstated. The suite was rewritten from human judgment of what is
actually worth remembering, deliberately breaking the buckets: vital
facts with no marker words, trivial facts carrying marker words, and
near-boundary judgments.

The independence claim rests ONLY on the marker-feature tests below:
a classifier that sees only marker features (hard mark present,
durable mark present, digit present), trained on half the suite,
cannot reproduce the held-out labels (accuracy under 0.7), and a
stub-mimicking marker predictor that reads only marker features
misses widely. If the labels were derived from markers, the trained
classifier would score high on held out rows (relabeling the suite
with the mimic scores 0.83 on the same split), so the 0.7 bound
fails closed: derivation cannot pass it. The scorer-competence
checks at the bottom of this file use RuleJudge as the scorer, so
they prove a stub matches the labels on hard cells; they are kept as
competence checks and are explicitly NOT independence evidence.
"""
import json
import re
from pathlib import Path

from uncluttered_memory.gate import (DURABLE_MARK, HARD_MARKS, Gate,
                                     RuleJudge)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.jsonl"

MARKERS = tuple(dict.fromkeys(HARD_MARKS + DURABLE_MARK))


def _load_importance():
    rows = [json.loads(line) for line in
            GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [c for c in rows if c["suite"] == "importance"]


def _has_marker(text: str) -> bool:
    low = text.lower()
    if re.search(r"\d", low) is not None:
        return True
    return any(m in low for m in MARKERS)


def _marker_features(text: str) -> tuple:
    """Only marker signals: hard mark, durable mark, digit. No text."""
    low = text.lower()
    return (
        any(m in low for m in HARD_MARKS),
        any(m in low for m in DURABLE_MARK),
        re.search(r"\d", low) is not None,
    )


def _majority(vals: list) -> int:
    """Most common label; ties break to the smaller label, fixed."""
    return max(set(vals), key=lambda v: (vals.count(v), -v))


def _stub_mimic(text: str) -> int:
    """What a pure marker-reader would predict: hard mark to 5,
    durable mark or digit to 4, chatter/sensitive low, else 2."""
    from uncluttered_memory.gate import (FILLER, _identity_claim, _laugh,
                                        _sensitive)
    t = " ".join(text.split())
    low = t.lower()
    if low in FILLER or len(t) <= 2:
        return 1
    if _laugh(low) or _identity_claim(t, low):
        return 1
    if _sensitive(low):
        return 2
    if any(m in low for m in HARD_MARKS):
        return 5
    if any(m in low for m in DURABLE_MARK) or re.search(r"\d", low):
        return 4
    return 2


def test_importance_marker_features_cannot_reproduce_labels():
    """Independence evidence (falsifiable): marker features do not
    determine the labels.

    A classifier that sees ONLY marker features is trained on one
    half of the suite (even rows by sorted id) and scored on the
    held-out half. Each feature vector predicts its training
    majority; unseen vectors fall back to the training global
    majority. Held-out accuracy must stay under 0.7, far below what
    derivation would give: relabeling this same suite with the
    marker mimic below scores 0.83 on the identical split, so a
    marker-derived label set FAILS this test. The interleaved split
    is fixed so the bound cannot be gamed by reordering rows.
    """
    cases = sorted(_load_importance(), key=lambda c: c["id"])
    assert len(cases) == 24
    train = [c for i, c in enumerate(cases) if i % 2 == 0]
    held = [c for i, c in enumerate(cases) if i % 2 == 1]
    assert len(train) == 12 and len(held) == 12
    by_vector: dict = {}
    for c in train:
        by_vector.setdefault(_marker_features(c["text"]), []).append(
            c["expect"])
    mapping = {vec: _majority(vals) for vec, vals in by_vector.items()}
    fallback = _majority([c["expect"] for c in train])
    good = sum(1 for c in held
               if mapping.get(_marker_features(c["text"]),
                              fallback) == c["expect"])
    accuracy = good / len(held)
    assert accuracy < 0.7, (good, len(held), mapping)


def test_importance_marker_mimic_misses_many():
    """Independence evidence (label side): a predictor that reads
    only marker features misses widely, so the labels cannot be a
    recoding of the markers."""
    cases = _load_importance()
    assert len(cases) == 24
    misses = [c["id"] for c in cases
              if _stub_mimic(c["text"]) != c["expect"]]
    assert len(misses) >= 6, misses


def test_scorer_competence_marker_free_vitals():
    """Scorer-competence check, NOT independence evidence.

    Uses RuleJudge as the scorer, so a pass proves the stub matches
    the labels on marker-free vitals. That is competence of the stub
    on hard cells, not proof the labels are independent of the stub;
    independence rests only on the label-side tests above.
    """
    gate = Gate(RuleJudge())
    vital = [c for c in _load_importance()
             if c["expect"] == 5 and not _has_marker(c["text"])]
    assert len(vital) >= 3
    good = [c["id"] for c in vital
            if gate.judge.vote(c["text"], [], []).importance == 5]
    assert len(good) >= 3, (vital, good)


def test_scorer_competence_marker_bearing_trivials():
    """Scorer-competence check, NOT independence evidence.

    Uses RuleJudge as the scorer, so a pass proves the stub matches
    the labels on marker-bearing trivials. That is competence of the
    stub on hard cells, not proof the labels are independent of the
    stub; independence rests only on the label-side tests above.
    """
    gate = Gate(RuleJudge())
    trivial = [c for c in _load_importance()
               if c["expect"] in (1, 2) and _has_marker(c["text"])]
    assert len(trivial) >= 3
    good = [c["id"] for c in trivial
            if gate.judge.vote(c["text"], [], []).importance == c["expect"]]
    assert len(good) >= 3, (trivial, good)
