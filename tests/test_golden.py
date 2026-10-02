"""Golden set integrity: hand-authored data, independent of the stub
generator, and reported separately from the synthetic bulk.

The headline numbers come from the golden set; the bulk set is a
self-consistency check. These tests pin the floor, the provenance, the
independence from eval/cases.py, and the headline wiring.
"""
import json
from pathlib import Path

from eval import run as evalmod
from eval.run import (GOLDEN_MIN_CASES, GOLDEN_PROVENANCE, SUITES,
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
    """No shared code path with the stub generator."""
    src = CASES_SRC.read_text(encoding="utf-8")
    assert GOLDEN_PROVENANCE not in src
    from eval.cases import build_cases
    generated = build_cases()
    gen_texts = set()
    for c in generated:
        for s in evalmod.case_strings(c):
            n = evalmod.normalize_for_compare(s)
            if len(n.split()) >= 3:
                gen_texts.add(n)
    golden = load_cases(GOLDEN)
    golden_texts = set()
    for c in golden:
        for s in evalmod.case_strings(c):
            n = evalmod.normalize_for_compare(s)
            if len(n.split()) >= 3:
                golden_texts.add(n)
    assert gen_texts.isdisjoint(golden_texts)
    assert all(c["provenance"] == GOLDEN_PROVENANCE for c in golden)


def test_golden_disjoint_from_bulk():
    frozen = load_cases(evalmod.CASES_FILE)
    golden = load_cases(GOLDEN)
    assert cross_split_overlap(frozen, golden) == set()


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


def test_run_eval_reports_golden_separately_with_headline(capsys):
    rc = evalmod.run_eval(str(evalmod.CASES_FILE), task="general-qa",
                          registry_path=None, root=ROOT)
    assert rc == 0
    out = capsys.readouterr().out
    assert "GOLDEN (hand-authored claim set" in out
    assert "BULK (synthetic-rule; self-consistency only" in out
    assert "admit      golden" in out
    assert "HEADLINE (golden, hand-authored):" in out
    assert "golden provenance=hand-authored" in out
    assert "golden sha256:" in out
    assert out.rstrip().endswith(
        "PASS: golden 0 failures, bulk 0 failures")


def test_failing_golden_case_drives_failure_and_headline(tmp_path, capsys):
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
    assert "HEADLINE (golden, hand-authored): 157/158 ok, 1 failures" in out
    assert "FAIL: golden 1 failures, bulk 0 failures" in out


def test_bulk_failure_fails_but_golden_stays_the_headline(tmp_path, capsys):
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
