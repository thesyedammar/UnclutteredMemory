"""P1 tests: supersede agreement veto, conflict marking (never tombstone),
tombstones for agreed supersede, calibration fingerprints, eval split
integrity, quarantine-state store, idempotent store, judge stubs."""
import json
import os
import time

import pytest
from uncluttered_memory import supersede as supmod
from uncluttered_memory.calibrate import CalibrationError, load_registry, calibrate_gate
from uncluttered_memory.gate import (FakeJudge, Gate, GateVote, JudgeClient,
                                      RuleJudge)
from uncluttered_memory.jev_client import (BadKey, JevError,
                                            JevJudgeClient,
                                            RateLimited,
                                            rate_limited_message,
                                            RuleRelationJudge)
from uncluttered_memory.store import Store

from eval.run import (find_bad_artifacts, run_eval, split_cases)
from eval import run as evalmod


def test_agreement_veto_no_tombstone():
    rj = supmod.FakeRelationJudge({("old", "new"): "supersede"})
    disagree = supmod.FakeRelationJudge({("old", "new"): "unrelated"})
    dec = supmod.decide("old", "new", rj, disagree)
    assert dec.action == "KEEP" and not dec.agreed
    assert "disagree-veto" in dec.reasons


def test_agreed_supersede_tombstones_with_provenance():
    s = Store()
    old = s.put("office is at 1 Main St", "user")
    new = s.put("office is at 2 Main St", "user")
    dec = supmod.decide("office is at 1 Main St", "office is at 2 Main St",
                        supmod.FakeRelationJudge(
                            {("office is at 1 Main St", "office is at 2 Main St"): "supersede"}),
                        supmod.FakeRelationJudge(
                            {("office is at 1 Main St", "office is at 2 Main St"): "supersede"}))
    assert supmod.apply(s, old, new, dec, actor="code", reason="addr")
    row = s.get(old)
    assert row[4] == new and row[5] == "addr" and row[6] == "code"
    assert [t for _, t, _ in s.live()] == ["office is at 2 Main St"]


def test_invalid_label_veto():
    class BadJudge(supmod.RelationJudge):
        def relation(self, old_text, new_text):
            return "nonsense"

    dec = supmod.decide("a", "b", BadJudge(), BadJudge())
    assert dec.action == "KEEP"
    assert "invalid-label-veto" in dec.reasons


def test_unrelated_agreed_keeps_both():
    rj = supmod.FakeRelationJudge({("a", "b"): "unrelated"})
    dec = supmod.decide("a", "b", rj, rj)
    assert dec.action == "KEEP" and dec.agreed and dec.relation == "unrelated"


def test_agreed_contradict_marks_both_never_tombstones():
    s = Store()
    old = s.put("I love tea", "user")
    new = s.put("I do not love tea anymore", "user")
    rj = supmod.FakeRelationJudge(
        {("I love tea", "I do not love tea anymore"): "contradict"})
    dec = supmod.decide("I love tea", "I do not love tea anymore", rj, rj)
    assert dec.action == "CONFLICT" and dec.agreed
    assert dec.relation == "conflict_unresolved"
    assert "never-tombstone" in " ".join(dec.reasons)
    assert supmod.apply(s, old, new, dec)
    assert s.get(old)[4] is None and s.get(new)[4] is None
    assert s.tombstoned() == []
    assert s.get(old)[7] == new and s.get(new)[7] == old
    assert s.conflicts() == [(old, new, "conflict_unresolved",
                              "conflict_unresolved", "code")]
    assert {t for _, t, _ in s.live()} == {"I love tea",
                                           "I do not love tea anymore"}


def test_agreed_conflict_unresolved_label_marks_both():
    s = Store()
    old = s.put("the gate opens at nine", "user")
    new = s.put("the gate is not opening at nine anymore", "user")
    rj = supmod.FakeRelationJudge(
        {("the gate opens at nine",
          "the gate is not opening at nine anymore"): "conflict_unresolved"})
    dec = supmod.decide("the gate opens at nine",
                        "the gate is not opening at nine anymore", rj, rj)
    assert dec.action == "CONFLICT" and dec.agreed
    assert supmod.apply(s, old, new, dec)
    assert s.tombstoned() == []
    assert len(s.conflicts()) == 1


def test_agreed_coexist_keeps_both_unmarked():
    s = Store()
    old = s.put("the kettle is blue", "user")
    new = s.put("the toaster is silver", "user")
    rj = supmod.FakeRelationJudge(
        {("the kettle is blue", "the toaster is silver"): "coexist"})
    dec = supmod.decide("the kettle is blue", "the toaster is silver", rj, rj)
    assert dec.action == "KEEP" and dec.agreed and dec.relation == "coexist"
    assert not supmod.apply(s, old, new, dec)
    assert s.conflicts() == []
    assert {t for _, t, _ in s.live()} == {"the kettle is blue",
                                           "the toaster is silver"}


def test_agreed_same_keeps_both_never_tombstones():
    s = Store()
    old = s.put("ship friday", "user")
    new = s.put("we ship friday", "user")
    rj = supmod.FakeRelationJudge({("ship friday", "we ship friday"): "same"})
    dec = supmod.decide("ship friday", "we ship friday", rj, rj)
    assert dec.action == "KEEP" and dec.agreed and dec.relation == "same"
    assert not supmod.apply(s, old, new, dec)
    assert s.tombstoned() == []


def test_disagree_on_conflict_vetoes_and_keeps_both():
    s = Store()
    old = s.put("standup at nine", "user")
    new = s.put("standup moved to ten", "user")
    a = supmod.FakeRelationJudge(
        {("standup at nine", "standup moved to ten"): "conflict_unresolved"})
    b = supmod.FakeRelationJudge(
        {("standup at nine", "standup moved to ten"): "supersede"})
    dec = supmod.decide("standup at nine", "standup moved to ten", a, b)
    assert dec.action == "KEEP" and not dec.agreed
    assert not supmod.apply(s, old, new, dec)
    assert s.tombstoned() == [] and s.conflicts() == []


def test_conflicts_user_scoped():
    s = Store()
    a1 = s.put("alice fact one", "user", user="alice")
    a2 = s.put("alice fact two", "user", user="alice")
    b1 = s.put("bob fact one", "user", user="bob")
    b2 = s.put("bob fact two", "user", user="bob")
    s.mark_conflict(a1, a2)
    s.mark_conflict(b1, b2)
    assert len(s.conflicts()) == 2
    assert s.conflicts(user="alice") == [(a1, a2, "conflict_unresolved",
                                          "conflict_unresolved", "code")]
    assert len(s.conflicts(user="bob")) == 1


def test_human_override_restore_and_retire():
    s = Store()
    old = s.put("meeting is at 3pm", "user")
    victim = s.put("meeting is at 4pm", "user")
    s.tombstone(old, victim, "supersede-agreed", "code")
    supmod.human_override(s, old, "restore", actor="human")
    assert s.get(old)[4] is None
    supmod.human_override(s, old, "retire", actor="human",
                          target_id=victim, reason="user said so")
    assert s.get(old)[4] == victim and s.get(old)[6] == "human"


def test_candidate_pairs_ordered():
    pairs = supmod.candidate_pairs([(3, "c"), (1, "a"), (2, "b")])
    assert pairs == [((1, "a"), (2, "b")), ((1, "a"), (3, "c")),
                     ((2, "b"), (3, "c"))]


def test_tombstone_retention_and_restore():
    s = Store()
    old = s.put("trip on monday", "user")
    new = s.put("trip on tuesday", "user")
    s.supersede(old, "trip on tuesday", "user")
    dead = s.tombstoned()
    assert dead and dead[0][0] == old and dead[0][3] == new
    s.restore(old)
    assert s.get(old)[4] is None
    assert {t for _, t, _ in s.live()} == {"trip on monday", "trip on tuesday"}


def test_calibrate_fingerprint_refusal(tmp_path):
    out = str(tmp_path / "registry.json")
    calibrate_gate([{"text": "keep 8%", "expect": "STORE"},
                    {"text": "lol", "expect": "DROP"}], "alpha", out,
                   lambda c: 0.9 if c["expect"] == "STORE" else 0.1)
    with pytest.raises(CalibrationError):
        load_registry(out, "beta")
    assert load_registry(out, "alpha")["task"] == "alpha"


def test_calibrate_refuses_test_split(tmp_path):
    out = str(tmp_path / "registry.json")
    with pytest.raises(CalibrationError):
        calibrate_gate([{"text": "x", "expect": "STORE", "split": "test"}],
                       "t", out, lambda c: 0.9)


def test_eval_50_50_split_disjoint_and_stratified():
    cases = [{"text": "My stop-loss is 8%", "expect": "STORE"},
             {"text": "Buy the whole exchange lol", "expect": "DROP"},
             {"text": "ok", "expect": "DROP"},
             {"text": "I am Batman", "expect": "DROP"},
             {"text": "prefer coffee", "expect": "STORE"},
             {"text": "hi", "expect": "DROP"},
             {"text": "weekend at 9pm", "expect": "STORE"},
             {"text": "prefer tea", "expect": "STORE"},
             {"text": "nope", "expect": "DROP"},
             {"text": "sure", "expect": "DROP"},
             {"text": "deadline is friday", "expect": "STORE"},
             {"text": "no", "expect": "DROP"},
             {"text": "thanks", "expect": "DROP"},
             {"text": "keep the stop-loss at the desk", "expect": "STORE"}]
    train, test = split_cases(cases)
    assert len(train) == len(test) == 7
    tr = {c["text"] for c in train}
    te = {c["text"] for c in test}
    assert tr.isdisjoint(te)
    assert sum(1 for c in train if c["expect"] == "STORE") == 3
    assert sum(1 for c in test if c["expect"] == "STORE") == 3


def test_eval_artifact_touching_test_exits_2(tmp_path):
    with open(evalmod.CASES_FILE) as f:
        cases = [json.loads(l) for l in f if l.strip()]
    train, test = split_cases(cases)
    sample = next(c for c in test if "text" in c)
    bad = tmp_path / "thresholds" / "general-qa.json"
    bad.parent.mkdir()
    bad.write_text(json.dumps(
        {"task": "general-qa", "trained_on": sample["text"]}))
    assert find_bad_artifacts(test, [str(bad)]) == [str(bad)]
    rc = run_eval(str(evalmod.CASES_FILE), task="general-qa",
                  registry_path=None, root=tmp_path)
    assert rc == 2


def test_rule_judge_unseen_input_sensible():
    g = Gate(RuleJudge())
    assert g.decide("Prefer standup notes at 10am").action == "STORE"
    assert g.decide("I am Batman").action == "DROP"
    assert g.decide("ok").action == "DROP"
    store = Store()
    store.quarantine("mystery", "uncertain-low-conf")
    assert store.quarantined() == [(1, "mystery", "uncertain-low-conf")]


def test_fake_judge_unseen_text_quarantines():
    g = Gate(FakeJudge({}))
    d = g.decide("any unseen text")
    assert d.action == "QUARANTINE"
    assert d.reasons == ["uncertain-low-conf"]


def test_quarantine_is_real_store_state():
    s = Store()
    s.quarantine("eligible for a 30% discount", "uncertain-low-conf", "web")
    s.quarantine("waitlist", "stop>=0.58", "web")
    rows = s.quarantined()
    assert [r[1] for r in rows] == ["eligible for a 30% discount", "waitlist"]
    fid = s.release(1, "chat")
    assert [t for _, t, _ in s.live()] == ["eligible for a 30% discount"]
    assert s.quarantined() == [(2, "waitlist", "stop>=0.58")]
    assert s.get(fid) is not None


class HaltingJudge(JudgeClient):
    def vote(self, text, neighbors, facts):
        raise RateLimited("quota")


def test_rate_limited_write_quarantines_pending():
    s = Store()
    action = s.admit("the sky is blue", "agent", Gate(HaltingJudge()))
    assert action == "QUARANTINE"
    assert s.quarantined() == [(1, "the sky is blue", "judge-halted")]
    assert s.live() == []


def test_admit_stores_through_gate():
    s = Store()
    action = s.admit("prefer standup at 9am", "chat", Gate(RuleJudge()))
    assert action == "STORE"
    assert [t for _, t, _ in s.live()] == ["prefer standup at 9am"]


def test_supersede_equal_text_noop():
    s = Store()
    old = s.put("ship friday", "user")
    assert s.supersede(old, "ship  friday", "user") == old
    assert s.tombstoned() == []
    assert [t for _, t, _ in s.live()] == ["ship friday"]


def test_put_updates_provenance_source():
    s = Store()
    fid = s.put("same fact", "email")
    assert s.put("  same  fact ", "chat") == fid
    assert s.get(fid)[2] == "chat"
    assert len(s.live()) == 1


def test_user_scoping():
    s = Store()
    a = s.put("stop-loss 8%", "user", user="alice")
    b = s.put("stop-loss 8%", "user", user="bob")
    assert a != b
    assert [t for _, t, _ in s.live(user="alice")] == ["stop-loss 8%"]
    assert len(s.live(user="bob")) == 1


def test_rule_relation_judge_features():
    rj = RuleRelationJudge()
    assert rj.relation("x", "x") == "same"
    assert rj.relation("old", "the plan changed now") == "supersede"
    assert rj.relation("love tea", "not tea anymore") == "conflict_unresolved"
    assert rj.relation("love tea", "no more tea") == "unrelated"


def test_jev_client_parse_errors_fail_closed(monkeypatch):
    j = JevJudgeClient(api_key="k")

    def bad(state, questions):
        return None
    monkeypatch.setattr(j, "evaluate", bad)
    with pytest.raises(JevError):
        j.vote("anything", [], [])


def test_jev_client_requires_key(monkeypatch):
    monkeypatch.delenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", raising=False)
    j = JevJudgeClient(api_key="")
    assert j.api_key == ""
    with pytest.raises(BadKey):
        j.evaluate({"m": {}}, {"p0": {"type": "noul", "instructions": "x"}})


def test_jev_client_parses_answer_variants():
    j = JevJudgeClient(api_key="k")
    assert j._answer_value({"noul": 0.24}, "noul") == 0.24
    assert j._answer_value({"probability": 0.24}, "noul") == 0.24
    assert j._answer_value({"choice": "r0"}, "choice") == "r0"
    assert j._answer_value({"level": 4}, "score") == 4


def test_jev_client_quota_surfaces_rate_limited(monkeypatch):
    import urllib.error
    j = JevJudgeClient(api_key="k")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "quota", {"retry-after": "120"}, None)  # type: ignore[arg-type]
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RateLimited) as ei:
        j._post(j.endpoint, {"model": j.model, "questions": {}})
    assert ei.value.retry_after == 120.0
    assert j.blocked_until > time.time()
    with pytest.raises(RateLimited):
        j._post(j.endpoint, {"model": j.model, "questions": {}})


def test_jev_client_vote_propagates_rate_limited(monkeypatch):
    import urllib.error
    j = JevJudgeClient(api_key="k")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RateLimited):
        j.vote("anything", [], [])
    assert "Retry later" in rate_limited_message(RateLimited("x"))


def test_model_allowlist_is_pinned():
    """Only jev-1.13-free may appear as a model name in the package."""
    import pathlib
    import tokenize
    bad = []
    for p in pathlib.Path("src/uncluttered_memory").glob("*.py"):
        with tokenize.open(p) as f:
            for tok in tokenize.generate_tokens(f.readline):
                if tok.type != tokenize.STRING:
                    continue
                if tok.string[:1] not in "'\"":
                    continue
                try:
                    flat = " ".join(eval(tok.string).split())
                except Exception:
                    continue
                if flat == "jev-1.13-free":
                    continue
                import re
                if re.search(r"\bjev-1\.13(?!-free)\b", flat) or "deepseek" in flat:
                    bad.append((str(p), flat[:80]))
    assert bad == [], bad
    from uncluttered_memory import jev_client as jc
    assert jc.DEFAULT_MODEL == "jev-1.13-free"
    assert not hasattr(jc, "DEFAULT_FALLBACK_MODEL")


def test_primary_vote_composes_answers(monkeypatch):
    j = JevJudgeClient(api_key="k")

    def ok(body, model):
        return {"answers": {"dur": {"noul": 0.9},
                            "imp": {"choice": "s4"},
                            "sens": {"noul": 0.0},
                            "stop": {"choice": "s1"}}}
    monkeypatch.setattr(j, "_ask_primary", ok)
    v = j.vote("stop-loss at 8%", [], [])
    assert v.durable >= 0.5 and v.importance == 5
    assert v.sensitive == 0.0 and v.stop == 0.0


def test_429_halts_no_fallback(monkeypatch):
    import urllib.error
    j = JevJudgeClient(api_key="k")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RateLimited):
        j.vote("anything", [], [])
    assert "Retry later" in rate_limited_message(RateLimited("x"))


def test_eval_cases_not_present_in_registry(tmp_path):
    p = str(tmp_path / "registry.json")
    calibrate_gate([{"text": "keep 10%", "expect": "STORE"},
                    {"text": "lol", "expect": "DROP"}], "alpha", p,
                   lambda c: 0.9 if c["expect"] == "STORE" else 0.1)
    reg = load_registry(p, "alpha")
    assert reg["train_f1"] >= 0.9


def test_run_eval_reports_metrics(tmp_path, capsys):
    cases = [{"suite": "admit", "kind": "durable-percent",
              "provenance": "synthetic-rule",
              "text": "My stop-loss is 8%", "expect": "STORE"},
             {"suite": "admit", "kind": "play", "provenance": "synthetic-rule",
              "text": "Buy the whole exchange lol", "expect": "DROP"},
             {"suite": "admit", "kind": "filler", "provenance": "synthetic-rule",
              "text": "ok", "expect": "DROP"},
             {"suite": "admit", "kind": "play", "provenance": "synthetic-rule",
              "text": "I am Batman", "expect": "DROP"}]
    p = tmp_path / "frozen.jsonl"
    with open(p, "w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    rc = run_eval(str(p), task="general-qa", registry_path=None, root=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "admit      train" in out and "admit      test" in out
    assert "importance train" in out and "rerank     test" in out
    assert "provenance=synthetic-rule" in out and "cases sha256" in out
    assert "cost per 1k" in out and "latency" in out
    assert "rule-stub" in out


def test_run_eval_rejects_missing_provenance(tmp_path, capsys):
    cases = [{"suite": "admit", "kind": "filler",
              "text": "ok", "expect": "DROP"}]
    p = tmp_path / "frozen.jsonl"
    with open(p, "w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    rc = run_eval(str(p), task="general-qa", registry_path=None, root=tmp_path)
    assert rc == 2
    out = capsys.readouterr().out
    assert "provenance" in out and "CASES ERROR" in out


def test_run_eval_rejects_unknown_suite(tmp_path, capsys):
    cases = [{"suite": "vibes", "kind": "x", "provenance": "synthetic-rule",
              "text": "anything", "expect": "STORE"}]
    p = tmp_path / "frozen.jsonl"
    with open(p, "w") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")
    rc = run_eval(str(p), task="general-qa", registry_path=None, root=tmp_path)
    assert rc == 2
    assert "unknown suite" in capsys.readouterr().out


def test_cli_calibrate_train_only(tmp_path):
    from uncluttered_memory import cli as climod
    out = str(tmp_path / "thresholds" / "general-qa.json")
    rc = climod.do_calibrate("general-qa", out)
    assert rc == 0
    reg = json.load(open(out))
    assert reg["task"] == "general-qa"
    assert "admit.durable" in reg["thresholds"]


@pytest.mark.skipif(
    not os.environ.get("HERMES_CUSTOM_OPENCODE_AI_API_KEY"),
    reason="live Jev integration needs the API key env")
def test_live_jev_noul_call():
    """One real native Jev noul call. Numeric score in range, or RateLimited."""
    j = JevJudgeClient()
    try:
        answers = j.evaluate(
            {"memory": {"text": "the sky is blue"}},
            {"p0": {"type": "noul",
                    "instructions": "Does memory.text state a durable fact?"}})
    except RateLimited:
        pytest.skip("free window rate-limited right now")
    score = j._answer_value(answers["p0"] or {}, "noul")
    assert isinstance(score, float) and 0.0 <= score <= 1.0