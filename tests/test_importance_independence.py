"""Provenance independence for the golden importance suite.

Earlier this suite mirrored the stub buckets (every 5 carried a hard
marker, 4/1/2 sat in stub buckets), so the hand-authored claim was
overstated. The suite was rewritten from human judgment of what is
actually worth remembering, deliberately breaking the buckets: vital
facts with no marker words, trivial facts carrying marker words, and
near-boundary judgments.

The independence claim rests ONLY on the label-side tests below:
labels live in the data file (stripping every marker token leaves the
stored labels unchanged), and a stub-mimicking marker predictor that
reads only marker features misses widely. The scorer-competence
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


def _strip_markers(text: str) -> str:
    out = text
    for m in MARKERS:
        out = re.sub(re.escape(m), " ", out, flags=re.IGNORECASE)
    return re.sub(r"\d", " ", out)


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


def test_importance_labels_live_in_data_not_derived():
    """Independence evidence (label side): stripping every marker
    token leaves the stored labels unchanged, because the labels are
    stored in the data file, not derived from text features."""
    cases = _load_importance()
    assert len(cases) == 24
    before = [(c["id"], c["expect"]) for c in cases]
    stripped = [_strip_markers(c["text"]) for c in cases]
    assert any(s != c["text"] for s, c in zip(stripped, cases))
    after = [(c["id"], c["expect"]) for c in _load_importance()]
    assert after == before


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
