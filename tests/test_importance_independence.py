"""Provenance independence for the golden importance suite.

Earlier this suite mirrored the stub buckets (every 5 carried a hard
marker, 4/1/2 sat in stub buckets), so the hand-authored claim was
overstated. The suite was rewritten from human judgment of what is
actually worth remembering, deliberately breaking the buckets: vital
facts with no marker words, trivial facts carrying marker words, and
near-boundary judgments.

The independence claim rests ONLY on the marker-feature tests below,
at two resolutions. The coarse test shows a classifier that sees
only three marker signals (hard mark present, durable mark present,
digit present), trained on half the suite, cannot reproduce the
held-out labels (accuracy under 0.7). The mirror-image test shows
the same holds when the classifier sees the FULL stub feature set:
every list and signal the offline scorer reads (filler and length,
laugh and identity-claim, sensitive pairings, each vital pairing,
each routine pairing, hard and durable marks, digits), extracted
with the scorer's own lists and predicates, trained on one half and
scored on the held-out half with the same memorization learner
(training majority per feature vector, training global majority
for unseen vectors). The interleaved split is fixed so the bound
cannot be gamed by reordering rows, and the 0.7 bound fails
closed: a label set derived from stub features would score high
on held out rows, so derivation cannot pass it.

A stub-mimicking marker predictor that reads only marker features
misses widely. If the labels were a recoding of the markers, the
mimic would agree with them; it does not. The scorer-competence
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


def _stub_features(text: str) -> tuple:
    """Mirror image of the offline scorer feature set, same signals.

    Every element mirrors one check RuleJudge.vote applies, in the
    same order, computed from the scorer's own module lists and
    predicates (imported, not recopied, so the two cannot drift):
    filler set and short length; laugh tokens; proper-noun identity
    claim; sensitive pairings; the vital top-level verdict plus each
    vital pairing (acute-care terms, care term inside a harm clause,
    jeopardy terms, stop-loss with a percent, limit or cap with a
    rate, legal term with a date or procedure, obligation noun with
    a date); the routine top-level verdict plus each routine
    pairing (standing words, every-recurrence, schedule verb with a
    time, capacity or rate, kept object with a locative, date of
    record); hard marks, durable marks, digits. No text beyond
    these signals, no label.
    """
    from uncluttered_memory import gate as gmod
    t = " ".join(text.split())
    low = t.lower()
    filler = low in gmod.FILLER or len(t) <= 2
    laugh = gmod._laugh(low)
    ident = gmod._identity_claim(t, low)
    sens = gmod._sensitive(low)
    vital = gmod._vital(low)
    routine = gmod._routine(low)
    acute = any(w in low for w in gmod._ACUTE)
    care_harm = (any(w in low for w in gmod._CARE)
                 and gmod._HARM_CLAUSE_RE.search(low) is not None)
    jeopardy = any(w in low for w in gmod._JEOPARDY)
    stop_loss = (("stop-loss" in low or "stoploss" in low
                  or "stop loss" in low) and "%" in low)
    limit_rate = (("limit" in low or " cap " in (" " + low + " "))
                  and ("lots" in low or "percent" in low or "%" in low))
    legal = (any(w in low for w in gmod._LEGAL)
             and (gmod._date_expr(low)
                  or any(w in low for w in gmod._PROCEDURE)))
    obligation = (any(w in low for w in gmod._OBLIGATION)
                  and gmod._date_expr(low))
    routine_word = any(w in low for w in gmod._ROUTINE_WORDS)
    every_rec = ("every" in low
                 and (gmod._date_expr(low) or "visit" in low
                      or "trip" in low or "morning" in low
                      or "evening" in low))
    sched = (any(v in low for v in gmod._SCHEDULE_VERBS)
             and (gmod._CLOCK_RE.search(low) is not None
                  or any(w in low for w in gmod._NAMED_DAYS)))
    capacity = any(w in low for w in gmod._CAPACITY)
    kept = (any(w in low for w in gmod._KEPT_OBJECTS)
            and any(w in low for w in gmod._LOCATIVE))
    record = (any(w in low for w in gmod._RECORD)
              and gmod._date_expr(low))
    hard = any(m in low for m in HARD_MARKS)
    durable = (any(m in low for m in DURABLE_MARK)
               or re.search(r"\d", low) is not None)
    digit = re.search(r"\d", low) is not None
    return (filler, laugh, ident, sens, vital, routine, acute,
            care_harm, jeopardy, stop_loss, limit_rate, legal,
            obligation, routine_word, every_rec, sched, capacity,
            kept, record, hard, durable, digit)


def test_importance_marker_features_cannot_reproduce_labels():
    """Independence evidence (coarse, falsifiable): marker features do
    not determine the labels.

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
    total = len(cases)
    assert total > 0, "no importance cases in the golden set"
    assert total >= 8, (
        "too few importance cases for a held-out split: %d" % total)
    train = [c for i, c in enumerate(cases) if i % 2 == 0]
    held = [c for i, c in enumerate(cases) if i % 2 == 1]
    assert len(train) == (total + 1) // 2 and len(held) == total // 2, (
        total, len(train), len(held))
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


def test_importance_full_stub_features_cannot_reproduce_labels():
    """Independence evidence (mirror image, falsifiable): the FULL
    stub feature set does not determine the labels.

    Same learner and same fixed interleaved split as the coarse
    test above, but the classifier sees _stub_features: every list
    and signal the offline scorer reads, extracted with the
    scorer's own lists and predicates. Each feature vector predicts
    its training majority; unseen vectors fall back to the training
    global majority. Held-out accuracy must stay under 0.7. The
    coarse test rules out substring derivation only (three marker
    signals against dozens of compositional scorer signals); this
    test rules out derivation from the full scorer signal set at
    the same strict bound. A label set tuned against the stub
    would score high here and FAIL this test; if it ever does,
    the labels must be rewritten until it cannot, because the
    independence claim would be false.
    """
    cases = sorted(_load_importance(), key=lambda c: c["id"])
    total = len(cases)
    assert total > 0, "no importance cases in the golden set"
    assert total >= 8, (
        "too few importance cases for a held-out split: %d" % total)
    train = [c for i, c in enumerate(cases) if i % 2 == 0]
    held = [c for i, c in enumerate(cases) if i % 2 == 1]
    assert len(train) == (total + 1) // 2 and len(held) == total // 2, (
        total, len(train), len(held))
    by_vector: dict = {}
    for c in train:
        by_vector.setdefault(_stub_features(c["text"]), []).append(
            c["expect"])
    mapping = {vec: _majority(vals) for vec, vals in by_vector.items()}
    fallback = _majority([c["expect"] for c in train])
    good = sum(1 for c in held
               if mapping.get(_stub_features(c["text"]),
                              fallback) == c["expect"])
    accuracy = good / len(held)
    assert accuracy < 0.7, (good, len(held), mapping)


def test_importance_marker_mimic_misses_many():
    """Independence evidence (label side): a predictor that reads
    only marker features misses widely, so the labels cannot be a
    recoding of the markers."""
    cases = _load_importance()
    total = len(cases)
    assert total > 0, "no importance cases in the golden set"
    misses = [c["id"] for c in cases
              if _stub_mimic(c["text"]) != c["expect"]]
    assert len(misses) >= max(1, total // 4), (misses, total)


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
