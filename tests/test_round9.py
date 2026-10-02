"""Round-9 harsh-judge coverage: one test per fix, end to end.

- _identity_claim reads lowercase identity claims via casefold.
- _importance_choice accepts s0..s4 and 1..5 explicitly, both ways.
- Spotcheck importance uses one shared vote path; disagreement shows.
- Store.error_count surfaces in CLI and eval conformance; nonzero is loud.
- Full CLI run on a temp DB, Recall.pack budget path, disk-backed DB.
"""
import importlib.util
from pathlib import Path

from eval import run as evalmod
from eval.run import load_cases, run_eval, total_error_count
from uncluttered_memory import cli as climod
from uncluttered_memory.gate import (Gate, GateVote, JudgeClient, RuleJudge,
                                      _identity_claim)
from uncluttered_memory.jev_client import JevJudgeClient
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _load_spotcheck():
    spec = importlib.util.spec_from_file_location(
        "live_spotcheck", ROOT / "scripts" / "live_spotcheck.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (5) identity claim casefolds: lowercase names still read as play.

def test_identity_claim_casefolds_lowercase_name():
    assert _identity_claim("i am zorro", "i am zorro") is True
    assert _identity_claim("i am mothra", "i am mothra") is True
    assert _identity_claim("I am Zorro", "i am zorro") is True


def test_identity_claim_lowercase_drops_through_gate():
    g = Gate(RuleJudge())
    assert g.decide("i am zorro").action == "DROP"
    assert g.decide("i am mothra").action == "DROP"
    assert g.decide("I am Zorro").action == "DROP"


def test_identity_claim_still_rejects_non_claims():
    assert _identity_claim("i am", "i am") is False
    assert _identity_claim("i am zorro2", "i am zorro2") is False
    assert _identity_claim("we are zorro", "we are zorro") is False


# (2) one choice-label contract: s0..s4 and 1..5, both ways.

def test_importance_choice_accepts_s_labels():
    conv = JevJudgeClient._importance_choice
    assert [conv("s%d" % i) for i in range(5)] == [1, 2, 3, 4, 5]


def test_importance_choice_accepts_design_scale_no_fail_closed():
    conv = JevJudgeClient._importance_choice
    for i in (1, 2, 3, 4, 5):
        assert conv(str(i)) == i
        assert conv(i) == i
    assert conv("S4") == 5
    assert conv(" s2 ") == 3


def test_importance_choice_rejects_garbage_closed():
    conv = JevJudgeClient._importance_choice
    for bad in ("s5", "s-1", "s", "", None, 0, 6, "x", "1.5",
                True, False, 3.0, [], "s4x"):
        assert conv(bad) == -1, bad


def test_live_vote_reads_design_scale_choice_labels(monkeypatch):
    j = JevJudgeClient(api_key="k")

    def ok_str(body, model):
        return {"answers": {"dur": {"noul": 0.9},
                            "imp": {"choice": "3"},
                            "sens": {"noul": 0.0},
                            "stop": {"choice": "s1"}}}

    monkeypatch.setattr(j, "_ask_primary", ok_str)
    assert j.vote("the plan is settled", [], []).importance == 3

    def ok_int(body, model):
        return {"answers": {"dur": {"noul": 0.9},
                            "imp": {"choice": 4},
                            "sens": {"noul": 0.0},
                            "stop": {"choice": "s1"}}}

    monkeypatch.setattr(j, "_ask_primary", ok_int)
    assert j.vote("the plan is settled", [], []).importance == 4


# (3) spotcheck importance: same vote path both sides, visible disagree.

def test_spotcheck_importance_uses_shared_vote_path():
    mod = _load_spotcheck()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    imp = [c for c in mod.sample_cases(cases, 20)
           if c["suite"] == "importance"]
    assert imp, "spotcheck sample must include importance cases"
    stub_judge = RuleJudge()
    for c in imp:
        assert mod.stub_verdict(c) == mod.importance_verdict(
            stub_judge, c["text"])
        assert mod.stub_verdict(c) == stub_judge.vote(
            c["text"], [], []).importance

    class Fixed(JudgeClient):
        def vote(self, text, neighbors, facts):
            return GateVote(0.9, 3, 0.0)

    fake = Fixed()
    for c in imp:
        assert mod.live_verdict(c, fake, None, None) == 3
        assert mod.live_verdict(c, fake, None, None) == fake.vote(
            c["text"], [], []).importance


class _FixedLiveJudge(JudgeClient):
    """Live-side stub: constant importance 3, always valid on 1..5."""

    def __init__(self):
        self.api_key = "test-key"
        self.model = "jev-1.13-free"

    def vote(self, text, neighbors, facts):
        return GateVote(0.9, 3, 0.0)


class _FakeLiveRel:
    def __init__(self, qid, instructions, criteria, rel):
        self._qid = qid
        self._instructions = instructions
        self._criteria = criteria
        self._rel = rel

    def _question_id_and_body(self):
        return (self._qid, {"type": "choice",
                            "instructions": self._instructions,
                            "criteria": dict(self._criteria)})

    def relation(self, old_text, new_text):
        return self._rel


def test_spotcheck_importance_disagreement_visible(monkeypatch, capsys):
    mod = _load_spotcheck()
    before = (ROOT / "tests" / "fixtures"
              / "live_votes_20261002.json").read_bytes()
    monkeypatch.setattr(mod, "JevJudgeClient", _FixedLiveJudge)
    monkeypatch.setattr(
        mod, "live_relation_pair",
        lambda *a, **k: (
            _FakeLiveRel("rel", "direct wording here",
                         {"a": "x", "b": "y"}, "coexist"),
            _FakeLiveRel("rel_confirm", "different slot wording here",
                         {"a": "p", "b": "q", "c": "r"}, "coexist")))
    rc = mod.main(["--n", "20", "--no-record"])
    assert rc == 0
    out = capsys.readouterr().out
    imp_lines = [ln for ln in out.splitlines() if ln.startswith("importance")]
    assert imp_lines, out
    assert any("live=3" in ln for ln in imp_lines)
    assert any("differ" in ln for ln in imp_lines), out
    assert "importance agreement (information only)" in out
    after = (ROOT / "tests" / "fixtures"
             / "live_votes_20261002.json").read_bytes()
    assert after == before, (
        "a dry run with a non-live judge must never overwrite "
        "recorded live votes")


# (4) error_count surfaces in CLI and eval conformance; nonzero is loud.

def test_cli_override_prints_error_count(tmp_path, capsys):
    db = tmp_path / "memory.db"
    s = Store(str(db))
    old = s.put("meeting is at 3pm", "user")
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "restore"])
    assert rc == 0
    assert "coding-bug count (Store.error_count): 0" in capsys.readouterr().out


def test_cli_nonzero_error_count_fails_loudly(tmp_path, capsys, monkeypatch):
    class BugStore:
        error_count = 2

        def __init__(self, *a, **k):
            pass

        def get(self, fid):
            return (fid, "t", "s", "local", None, None, None, None)

    monkeypatch.setattr(climod, "Store", BugStore)
    monkeypatch.setattr(climod.supmod, "human_override",
                        lambda *a, **k: None)
    rc = climod.main(["override", "--db", str(tmp_path / "m.db"),
                      "--fact-id", "1", "--action", "restore"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "CODING-BUG COUNT NONZERO (Store.error_count): 2" in out


def test_total_error_count_sums_stores():
    class S:
        def __init__(self, n):
            self.error_count = n

    assert total_error_count([S(0), S(0)]) == 0
    assert total_error_count([S(1), S(2)]) == 3
    assert total_error_count([object()]) == 0


def test_eval_conformance_prints_coding_bug_count(capsys):
    rc = run_eval()
    assert rc == 0
    out = capsys.readouterr().out
    assert ("coding-bug count (Store.error_count across eval stores): 0"
            in out)
    assert out.splitlines()[-1] == "PASS: golden 0 failures, bulk 0 failures"


def test_eval_nonzero_error_count_fails_loudly(tmp_path, capsys, monkeypatch):
    class BuggyStore(Store):
        def put(self, *a, **k):
            self.error_count += 1
            return super().put(*a, **k)

    monkeypatch.setattr(evalmod, "Store", BuggyStore)
    rc = run_eval(root=tmp_path, golden_path=None)
    assert rc == 1
    out = capsys.readouterr().out
    assert "CODING-BUG COUNT NONZERO" in out


# (6) three end-to-end tests.

def test_cli_full_run_against_temp_db(tmp_path, capsys):
    db = tmp_path / "cli-e2e.db"
    s = Store(str(db))
    old = s.put("dentist appointment at 3pm Tuesday", "user")
    new = s.put("dentist appointment at 4pm Tuesday", "user")
    s.tombstone(old, new, "supersede-agreed", "code")
    assert db.exists()
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "restore"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "restore by human" in out
    assert "coding-bug count (Store.error_count): 0" in out
    assert {t for _, t, *_ in Store(str(db)).live()} == {
        "dentist appointment at 3pm Tuesday",
        "dentist appointment at 4pm Tuesday"}
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "retire", "--target-id", str(new),
                      "--reason", "user said so"])
    assert rc == 0
    row = Store(str(db)).get(old)
    assert row[4] == new and row[5] == "user said so" and row[6] == "human"
    assert [t for _, t, *_ in Store(str(db)).live()] == [
        "dentist appointment at 4pm Tuesday"]


def test_recall_pack_budget_path_end_to_end():
    r = Recall()
    scored = [("alpha fact about the dentist at 3pm", 0.95),
              ("beta note about the dentist at 4pm", 0.90),
              ("gamma unrelated low whisper", 0.10)]
    selected = r.select(scored)
    assert selected == [t for t, _ in scored[:2]]
    tight = len(selected[0]) + 1 + 2
    assert tight < len(selected[0]) + 1 + len(selected[1]) + 1
    packed = r.pack(selected, budget_chars=tight)
    assert packed == selected[0]
    assert selected[1] not in packed
    assert len(packed) <= tight
    whole = r.pack(selected)
    assert whole == "\n".join(selected)


def test_disk_backed_sqlite_file_db_write_reopen_tombstone(tmp_path):
    db = tmp_path / "memory.db"
    s1 = Store(str(db))
    a = s1.put("standup moved to half past nine on weekdays", "agent")
    b = s1.put("standup moved to half past ten on weekdays", "agent")
    s1.tombstone(a, b, "supersede-agreed", "code")
    s1.db.close()
    assert db.exists() and db.stat().st_size > 0
    s2 = Store(str(db))
    assert [t for _, t, *_ in s2.live()] == [
        "standup moved to half past ten on weekdays"]
    tomb = s2.tombstoned()
    assert len(tomb) == 1 and tomb[0][0] == a and tomb[0][3] == b
    row = s2.get(a)
    assert row[5] == "supersede-agreed" and row[6] == "code"
    s2.restore(a)
    s2.db.close()
    s3 = Store(str(db))
    assert {t for _, t, *_ in s3.live()} == {
        "standup moved to half past nine on weekdays",
        "standup moved to half past ten on weekdays"}
    assert s3.tombstoned() == []
    s3.db.close()
