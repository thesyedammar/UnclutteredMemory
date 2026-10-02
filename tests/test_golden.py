"""Golden set integrity: hand-authored data, independent of the stub
generator, and reported separately from the synthetic bulk.

The conformance numbers come from the golden set: contract
conformance (the system reproduces frozen human judgments), NOT
accuracy or memory quality. The bulk set is a self-consistency check.
These tests pin the floor, the provenance, the independence from
eval/cases.py, and the conformance wiring.
"""
import json
from collections import Counter
from pathlib import Path

from eval import run as evalmod
from eval.run import (GOLDEN_MIN_CASES, GOLDEN_MIN_PER_SUITE,
                      GOLDEN_PROVENANCE, SUITES,
                      cross_split_overlap, load_cases, load_golden)
from uncluttered_memory import supersede as supmod
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.jev_client import offline_relation_pair
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.jsonl"
CASES_SRC = ROOT / "eval" / "cases.py"


def _write_cases(path, cases):
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    return path


#: Documented golden census, kept in sync with the README and the
#: GOLDEN_MIN_PER_SUITE comment in eval/run.py. Any hand edit that
#: adds or removes a golden case must update this census and the
#: README together; the test below fails otherwise.
GOLDEN_TOTAL_CASES = 160
GOLDEN_SUITE_COUNTS = {
    "admit": 56,
    "importance": 24,
    "dedupe": 20,
    "contradict": 23,
    "supersede": 23,
    "rerank": 14,
}


def test_golden_total_and_per_suite_counts_pinned():
    """The 160 total and the per-suite census hold exactly as stated."""
    cases, err = load_golden(GOLDEN)
    assert err is None
    by_suite = Counter(c["suite"] for c in cases)
    assert len(cases) == GOLDEN_TOTAL_CASES, len(cases)
    assert dict(by_suite) == GOLDEN_SUITE_COUNTS, dict(by_suite)
    for suite, floor in GOLDEN_MIN_PER_SUITE.items():
        assert by_suite[suite] >= floor, (suite, by_suite[suite], floor)


def test_golden_thin_suite_rejected(tmp_path):
    """One gutted suite fails even when the global total clears 120."""
    cases, err = load_golden(GOLDEN)
    assert err is None
    keep = [c for c in cases if c["suite"] != "rerank"]
    keep += [c for c in cases if c["suite"] == "rerank"][:5]
    assert len(keep) >= GOLDEN_MIN_CASES
    assert {c["suite"] for c in keep} == set(SUITES)
    gpath = _write_cases(tmp_path / "golden.jsonl", keep)
    _, gerr = load_golden(gpath)
    assert gerr is not None and "per-suite floor" in gerr, gerr


def test_golden_set_exists_with_floor_and_all_suites():
    cases, err = load_golden(GOLDEN)
    assert err is None
    assert len(cases) >= GOLDEN_MIN_CASES >= 120
    assert {c["suite"] for c in cases} == set(SUITES)
    assert all(c["provenance"] == GOLDEN_PROVENANCE for c in cases)
    assert all(c["kind"] for c in cases)
    for c in cases:
        assert c["id"].startswith("g-")
        if c["suite"] in ("contradict", "supersede"):
            assert "old" in c and "new" in c and "expect" in c
        elif c["suite"] == "dedupe":
            assert "text" in c and "candidate" in c and "expect" in c
        elif c["suite"] == "rerank":
            assert "candidates" in c and "expect" in c
        else:
            assert "text" in c and "expect" in c


def test_golden_labels_are_data_not_generated():
    """No shared code path with the stub generator, at any length."""
    src = CASES_SRC.read_text(encoding="utf-8")
    assert GOLDEN_PROVENANCE not in src
    from eval.cases import build_cases
    generated = build_cases()
    gen_texts = set()
    for c in generated:
        for s in evalmod.case_strings(c):
            n = evalmod.normalize_for_compare(s)
            if n:
                gen_texts.add(n)
    golden = load_cases(GOLDEN)
    golden_texts = set()
    for c in golden:
        for s in evalmod.case_strings(c):
            n = evalmod.normalize_for_compare(s)
            if n:
                golden_texts.add(n)
    assert gen_texts.isdisjoint(golden_texts)
    assert all(c["provenance"] == GOLDEN_PROVENANCE for c in golden)


def test_golden_disjoint_from_bulk():
    frozen = load_cases(evalmod.CASES_FILE)
    golden = load_cases(GOLDEN)
    assert cross_split_overlap(frozen, golden) == set()


def test_cross_split_overlap_catches_short_thanks_leak():
    """Sub-three-token reuse is an exact-match leak, not a free pass.

    The old three-token floor ignored single-token play and filler
    texts, exactly where the golden claim set lives. A bulk side
    carrying "thanks" and a golden side carrying "Thanks" must
    overlap after normalization.
    """
    bulk = [{"id": "b1", "suite": "admit", "kind": "filler",
             "provenance": "synthetic-rule", "text": "thanks",
             "expect": "DROP"}]
    golden = [{"id": "g1", "suite": "admit", "kind": "filler",
               "provenance": "hand-authored", "text": "Thanks",
               "expect": "DROP"}]
    assert cross_split_overlap(bulk, golden) == {"thanks"}
    same = [dict(golden[0], id="g2", text="no"),
            dict(bulk[0], id="b2", text="No")]
    assert cross_split_overlap([same[1]], [same[0]]) == {"no"}


def test_cross_split_overlap_catches_short_two_token_leak():
    """Two-token reuse counts too: "got it" versus "GOT IT" overlaps."""
    bulk = [{"id": "b1", "suite": "admit", "kind": "filler",
             "provenance": "synthetic-rule", "text": "got it",
             "expect": "DROP"}]
    golden = [{"id": "g1", "suite": "admit", "kind": "filler",
               "provenance": "hand-authored", "text": "GOT IT",
               "expect": "DROP"}]
    assert cross_split_overlap(bulk, golden) == {"got it"}


def test_cross_split_overlap_still_empty_without_reuse():
    """Distinct short texts do not overlap: kk and will do are clean."""
    bulk = [{"id": "b1", "suite": "admit", "kind": "filler",
             "provenance": "synthetic-rule", "text": "thanks",
             "expect": "DROP"}]
    golden = [{"id": "g1", "suite": "admit", "kind": "filler",
               "provenance": "hand-authored", "text": "kk",
               "expect": "DROP"}]
    assert cross_split_overlap(bulk, golden) == set()


def test_every_golden_case_passes_the_offline_system():
    """The claim set, scored the same way the eval scores it."""
    gate = Gate(RuleJudge())
    cases, err = load_golden(GOLDEN)
    assert err is None
    fails = []
    for c in cases:
        s = c["suite"]
        if s == "admit":
            got = gate.decide(c["text"], importance_min=3).action
        elif s == "importance":
            got = gate.judge.vote(c["text"], [], []).importance
        elif s == "dedupe":
            st = Store()
            a = st.put(c["text"], "eval")
            b = st.put(c["candidate"], "eval")
            got = "DUP" if a == b else "DISTINCT"
        elif s in ("contradict", "supersede"):
            got = supmod.decide(c["old"], c["new"],
                                *offline_relation_pair()).action
        elif s == "rerank":
            got = Recall().select(
                [(t, float(v)) for t, v in c["candidates"]],
                gate=float(c.get("gate", 0.58)))
        else:
            raise AssertionError("unknown suite %r" % s)
        if got != c["expect"]:
            fails.append((c["id"], c["expect"], got))
    assert fails == []


def test_golden_relation_claims_meet_the_strict_minimum():
    """Every destructive or marking golden claim shares a readable slot.

    The strict judge only reads a marker as same-slot with
    RELATION_SHARED_TOKENS_MIN shared content tokens beyond stopwords
    and numbers. A claim set that demands TOMBSTONE or CONFLICT from a
    one-token pair would demand what the documented contract forbids,
    so destructive claims must carry the shared slot unambiguously.
    Single-token near-misses live in the KEEP cases and in
    tests/test_relation_boundary.py.
    """
    from uncluttered_memory import thresholds as th
    from uncluttered_memory.jev_client import _shared_content

    cases, err = load_golden(GOLDEN)
    assert err is None
    checked = 0
    for c in cases:
        if c["suite"] not in ("supersede", "contradict"):
            continue
        if c["expect"] not in ("TOMBSTONE", "CONFLICT"):
            continue
        checked += 1
        assert _shared_content(c["old"], c["new"]) >= \
            th.RELATION_SHARED_TOKENS_MIN, c["id"]
    assert checked >= 20


def test_run_eval_reports_golden_separately_with_conformance(capsys):
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=ROOT)
    assert rc == 0
    out = capsys.readouterr().out
    assert "GOLDEN (hand-authored conformance set" in out
    assert "BULK (synthetic-rule; self-consistency only" in out
    assert "admit      golden" in out
    assert "CONTRACT CONFORMANCE (golden, hand-authored):" in out
    assert "NOT accuracy or memory quality" in out
    assert "independent-rater agreement (recorded live jev-1.13-free" in out
    assert "10/24 = 41.7%" in out
    assert "golden provenance=hand-authored" in out
    assert "golden sha256:" in out
    assert out.rstrip().endswith(
        "PASS: golden 0 failures, bulk 0 failures")


def test_failing_golden_case_drives_failure_and_conformance(tmp_path, capsys):
    cases = load_cases(GOLDEN)
    first = cases[0]
    first["expect"] = "DROP" if first["expect"] != "DROP" else "STORE"
    gpath = _write_cases(tmp_path / "golden.jsonl", cases)
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=tmp_path,
                          golden_path=str(gpath))
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] GOLDEN" in out
    assert (("CONTRACT CONFORMANCE (golden, hand-authored): %d/%d ok, "
             "1 failures" % (len(cases) - 1, len(cases)))) in out
    assert "FAIL: golden 1 failures, bulk 0 failures" in out


def test_bulk_failure_fails_but_golden_stays_the_conformance_number(tmp_path, capsys):
    bad = [{"id": "b1", "suite": "admit", "kind": "x",
            "provenance": "synthetic-rule", "text": "thanks",
            "expect": "STORE"}]
    bpath = _write_cases(tmp_path / "bulk.jsonl", bad)
    rc = evalmod.run_eval(str(bpath), task="general-qa",
                          registry_path=None, root=tmp_path)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] BULK" in out
    assert "FAIL: golden 0 failures, bulk 1 failures" in out


def test_missing_golden_is_a_hard_error(tmp_path, capsys):
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=tmp_path,
                          golden_path=str(tmp_path / "absent.jsonl"))
    assert rc == 2
    assert "GOLDEN ERROR" in capsys.readouterr().out


def test_golden_wrong_provenance_rejected(tmp_path, capsys):
    bad = [{"id": "g-x", "suite": "admit", "kind": "x",
            "provenance": "synthetic-rule", "text": "ok", "expect": "DROP"}]
    gpath = _write_cases(tmp_path / "golden.jsonl", bad)
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=tmp_path,
                          golden_path=str(gpath))
    assert rc == 2
    out = capsys.readouterr().out
    assert "GOLDEN ERROR" in out and "provenance" in out


def test_golden_floor_enforced(tmp_path, capsys):
    small = [{"id": "g-x", "suite": "admit", "kind": "x",
              "provenance": GOLDEN_PROVENANCE, "text": "ok",
              "expect": "DROP"}]
    gpath = _write_cases(tmp_path / "golden.jsonl", small)
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=tmp_path,
                          golden_path=str(gpath))
    assert rc == 2
    assert "documented floor" in capsys.readouterr().out


def test_golden_missing_suite_rejected(tmp_path, capsys):
    cases, err = load_golden(GOLDEN)
    assert err is None
    only_admit = [c for c in cases if c["suite"] == "admit"]
    # pad to the floor so the suite check is what fires
    padded = list(only_admit)
    while len(padded) < GOLDEN_MIN_CASES:
        c = dict(only_admit[len(padded) % len(only_admit)])
        c["id"] = "g-pad-%04d" % len(padded)
        padded.append(c)
    gpath = _write_cases(tmp_path / "golden.jsonl", padded)
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=tmp_path,
                          golden_path=str(gpath))
    assert rc == 2
    assert "misses suite" in capsys.readouterr().out
