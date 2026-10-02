"""Auto-activation bridge: free screen plus committee verdict on writes.

After every fresh Store.put insert the free suspicion screen runs
against live rows in the same user scope; flagged pairs go to the
existing committee (offline Strict+Lenient pair by default, the
live dual-Jev path where wired) and the verdict applies with
auto-spot provenance. Offline tests run with fixture votes only:
no test here touches the network (one test proves the offline path
with urlopen rigged to fail).
"""
import inspect
import json
from unittest import mock

import pytest

from uncluttered_memory import autospot
from uncluttered_memory import supersede as supmod
from uncluttered_memory import thresholds as th
from uncluttered_memory.gate import FakeJudge, Gate, GateVote
from uncluttered_memory.jev_client import (RateLimited,
                                           live_relation_pair)
from uncluttered_memory.server import MemoryApp, RateLimiter
from uncluttered_memory.store import Store


class _Replay:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_live(choices_by_qid, calls=None):
    def fake_urlopen(req, timeout=None):
        if calls is not None:
            calls.append(json.loads(req.data.decode()))
        questions = json.loads(req.data.decode()).get("questions", {})
        assert len(questions) == 1
        qid = next(iter(questions))
        body = json.dumps(
            {"answers": {qid: {"choice": choices_by_qid[qid]}}}).encode()
        return _Replay(body)

    return mock.patch("urllib.request.urlopen", fake_urlopen)


OFFICE_OLD = "the office is at 1 Main St"
OFFICE_MOVED = "the office moved to 2 Main St"
RUNS_OLD = "I love morning runs"
RUNS_STOPPED = "I do not love morning runs anymore"
KETTLE = "the kettle is blue"
TOASTER = "the toaster is silver"


def test_screen_flags_same_slot_update_with_marker():
    assert autospot.is_suspicious(OFFICE_OLD, OFFICE_MOVED) is True
    assert autospot.suspicion_score(OFFICE_OLD, OFFICE_MOVED) == pytest.approx(
        0.40)


def test_screen_skips_disjoint_pair_below_minimum():
    assert autospot.suspicion_score(KETTLE, TOASTER) == pytest.approx(
        1.0 / 3.0)
    # Zero token overlap: unrelated wording the committee never sees.
    assert autospot.is_suspicious("the kettle is blue",
                                  "midnight owls hunt silently") is False


def test_screen_never_flags_exact_duplicates():
    assert autospot.is_suspicious("the cat sat", "the  cat sat") is False


def test_screen_needs_a_change_signal_or_differing_detail():
    # Same content tokens, only stopwords differ, no marker, no
    # number move: overlap without any change signal reads as no
    # suspicion.
    assert autospot.is_suspicious("the cat sat on the mat",
                                  "a cat sat on a mat") is False
    # A bare number swap moves the slot value with no marker
    # wording: the screen nominates it and the committee decides.
    assert autospot.is_suspicious(OFFICE_OLD,
                                  "the office is at 2 Main St") is True
    assert autospot.number_detail_tokens("demo at 4pm") == {"4pm"}
    assert autospot.number_detail_differs("demo at 4pm",
                                          "demo at 5pm") is True
    assert autospot.is_suspicious(
        "sprint demo is every thursday at 4pm",
        "sprint demo is every thursday at 5pm") is True


def test_number_swap_nominates_but_committee_keeps_both():
    # Marker-free number swaps are nominated, then the offline pair
    # agrees they are unrelated (no update marker on either side):
    # veto to KEEP, both facts live, nothing marked.
    s = Store()
    old_id = s.put("the office is at 1 Main St", "user")
    new_id = s.put("the office is at 2 Main St", "user")
    assert s.tombstoned() == [] and s.conflicts() == []
    assert s.get(old_id)[4] is None and s.get(new_id)[7] is None
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["checked"] == 1
    assert s.last_autospot["kept"] == [old_id]


def test_stale_backfill_never_tombstones_newer_fact():
    # Directionality by insert order: the existing row is the old
    # side, the fresh row the new side. Stale wording arriving late
    # is nominated (the number moved) but the committee reads the
    # marker-free fresh text as no revision and vetoes to KEEP.
    s = Store()
    newer_id = s.put("the office moved to 2 Main St", "user")
    stale_id = s.put("the office is at 1 Main St", "user")
    assert s.tombstoned() == []
    assert s.get(newer_id)[4] is None and s.get(stale_id)[4] is None
    assert {t for _, t, *_ in s.live()} == {
        "the office moved to 2 Main St", "the office is at 1 Main St"}
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["checked"] == 1
    assert s.last_autospot["kept"] == [newer_id]


def test_agreed_keep_carries_relation_veto_carries_veto_keep():
    # Agreed benign verdicts record their relation; only genuine
    # disagreement reads "veto-keep".
    s = Store()
    s.put(KETTLE, "user")
    s.put(TOASTER, "user")
    assert isinstance(s.last_autospot, dict)
    kept = s.last_autospot["outcomes"][0]
    assert kept["applied"] is False and kept["action"] == "KEEP"
    assert kept["reason"] == "unrelated-auto-spot"

    old = "the studio opens at nine"
    new = "the studio no longer opens at nine, it opens at ten now"
    s2 = Store()
    s2.put(old, "user")
    s2.put(new, "user")
    assert isinstance(s2.last_autospot, dict)
    vetoed = s2.last_autospot["outcomes"][0]
    assert vetoed["applied"] is False and vetoed["action"] == "KEEP"
    assert vetoed["reason"] == "veto-keep"


def test_old_side_negation_nominates_via_detail_signals():
    # Markers read from the new side only (revision direction);
    # the old-side negation still nominates through the symmetric
    # detail signals, then the committee decides.
    old, new = "I stopped morning runs", "I love morning runs"
    assert autospot.has_change_signal(new) is False
    assert autospot.is_suspicious(old, new) is True
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    assert s.tombstoned() == [] and s.conflicts() == []
    assert {t for _, t, *_ in s.live()} == {old, new}
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["kept"] == [old_id]


def test_serve_cli_exposes_auto_spot_knob(capsys, tmp_path, monkeypatch):
    import uncluttered_memory.server as srvmod
    from uncluttered_memory.cli import main
    seen = {}

    class _Once:
        def __init__(self, store):
            seen["auto"] = store._auto_spot

        def serve_forever(self):
            raise KeyboardInterrupt()

    def fake_serve(host, port, store, judge, kill_file=None):
        return _Once(store)

    monkeypatch.setattr(srvmod, "serve", fake_serve)
    db = str(tmp_path / "cli.db")
    assert main(["serve", "--db", db]) == 0
    assert seen["auto"] is True
    assert main(["serve", "--db", db, "--no-auto-spot"]) == 0
    assert seen["auto"] is False
    out = capsys.readouterr().out
    assert "auto-spot on (offline committee)" in out
    assert "auto-spot off" in out


def test_committee_coding_bug_propagates_loudly():
    # A raising committee judge is a coding bug, never a quiet KEEP:
    # put propagates, the fresh row stays live, nothing is marked.
    class _Boom(supmod.RelationJudge):
        def relation(self, old_text, new_text):
            raise RuntimeError("committee blew up")

    s = Store(auto_spot=False)
    s.put(RUNS_OLD, "user", auto_spot=False)
    with pytest.raises(RuntimeError):
        s.put(RUNS_STOPPED, "user", auto_spot=True,
              relation_pair=(_Boom(), _Boom()))
    assert {t for _, t, *_ in s.live()} == {RUNS_OLD, RUNS_STOPPED}
    assert s.tombstoned() == [] and s.conflicts() == []


def test_screen_minimum_is_a_parameter_defaulting_to_thresholds():
    sig = inspect.signature(autospot.is_suspicious)
    assert sig.parameters["min_jaccard"].default == th.AUTOSPOT_MIN_JACCARD
    assert autospot.is_suspicious(KETTLE, TOASTER, min_jaccard=0.30) is True
    assert autospot.is_suspicious(KETTLE, TOASTER, min_jaccard=0.34) is False


def test_candidates_stay_in_user_scope_and_skip_the_new_row():
    s = Store()
    s.put("the office key is brass", "user", user="ali")
    other = s.put("the office key is brass", "user", user="bea")
    assert other is not None
    new_id = s.put("the office key changed to steel", "user", user="bea",
                   relation_pair=supmod.FakeRelationJudge({}),
                   auto_spot=False)
    cands, dropped = autospot.find_candidates(s, new_id,
                                              "the office key changed to steel",
                                              "bea")
    assert dropped == 0
    assert [c[0] for c in cands] == [other]
    assert new_id not in [c[0] for c in cands]


def test_candidates_cap_keeps_strongest_first_and_counts_dropped():
    s = Store(auto_spot=False)
    ids = [s.put(t, "user", auto_spot=False) for t in (
        "standup moved to half past nine on weekdays",
        "standup moved to half past nine on fridays",
        "the standup moved to half past nine")]
    assert len({t for _, t, *_ in s.live()}) == 3  # all DISTINCT rows
    new = "standup moved to half past ten on weekdays"
    cands, dropped = autospot.find_candidates(
        s, 9999, new, "local",
        min_jaccard=th.AUTOSPOT_MIN_JACCARD, max_pairs=1)
    assert dropped == 2
    assert len(cands) == 1 and cands[0][0] == ids[0]
    full, _ = autospot.find_candidates(
        s, 9999, new, "local",
        min_jaccard=th.AUTOSPOT_MIN_JACCARD, max_pairs=5)
    assert len(full) == 3
    assert [c[2] for c in full] == sorted([c[2] for c in full],
                                         reverse=True)
    assert full[0][0] == ids[0]


def test_offline_agreed_supersede_tombstones_with_auto_provenance():
    s = Store()
    old_id = s.put(OFFICE_OLD, "user")
    first = s.last_autospot  # fresh row, nothing to screen against yet
    assert isinstance(first, dict) and first["flagged"] == 0
    new_id = s.put(OFFICE_MOVED, "user")
    row = s.get(old_id)
    assert row[4] == new_id
    assert row[5] == "supersede-auto-spot" and row[6] == "auto-spot"
    assert [t for _, t, *_ in s.live()] == [OFFICE_MOVED]
    summary = s.last_autospot
    assert isinstance(summary, dict)
    assert summary["checked"] == 1 and summary["tombstoned"] == [old_id]
    assert summary["halted"] is False and summary["rate_limited"] is False
    assert summary["outcomes"][0]["applied"] is True


def test_offline_agreed_clash_marks_both_never_tombstones():
    s = Store()
    old_id = s.put(RUNS_OLD, "user")
    new_id = s.put(RUNS_STOPPED, "user")
    assert s.tombstoned() == []
    assert s.get(old_id)[7] == new_id and s.get(new_id)[7] == old_id
    assert len(s.conflicts()) == 1
    _o, _n, _rel, reason, actor = s.conflicts()[0]
    assert reason == "conflict_unresolved-auto-spot" and actor == "auto-spot"
    assert {t for _, t, *_ in s.live()} == {RUNS_OLD, RUNS_STOPPED}
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["conflicts"] == [old_id]


def test_offline_disagreement_vetoes_and_writes_nothing():
    # Strict reads the negation as a clash, lenient reads the update
    # wording as a supersede: genuine disagreement, veto.
    old = "the studio opens at nine"
    new = "the studio no longer opens at nine, it opens at ten now"
    s = Store()
    old_id = s.put(old, "user")
    new_id = s.put(new, "user")
    assert s.tombstoned() == [] and s.conflicts() == []
    assert s.get(old_id)[7] is None and s.get(new_id)[7] is None
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["checked"] == 1
    assert s.last_autospot["kept"] == [old_id]


def test_offline_unrelated_agreement_keeps_both():
    # Overlap plus differing detail flags the screen, then the
    # committee agrees the pair is unrelated: both stay live.
    s = Store()
    old_id = s.put(KETTLE, "user")
    new_id = s.put(TOASTER, "user")
    assert s.tombstoned() == [] and s.conflicts() == []
    assert {t for _, t, *_ in s.live()} == {KETTLE, TOASTER}
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["kept"] == [old_id]


def test_fixture_votes_drive_the_bridge():
    # Deterministic control: fixture votes force TOMBSTONE on a pair
    # the shipped pair would keep, proving the wiring applies the
    # committee verdict instead of the screen.
    s = Store(auto_spot=False)
    old_id = s.put(KETTLE, "user", auto_spot=False)
    new_id = s.put(TOASTER, "user", auto_spot=False)
    pair = supmod.FakeRelationJudge({(KETTLE, TOASTER): "supersede"})
    summary = autospot.run_after_put(s, new_id, TOASTER, "local",
                                    relation_pair=(pair, pair))
    assert summary["tombstoned"] == [old_id]
    assert s.get(old_id)[4] == new_id


def test_bridge_runs_only_on_fresh_inserts():
    s = Store()
    a = s.put("pack the picnic hamper for sunday", "email")
    assert isinstance(s.last_autospot, dict)  # fresh row, zero pairs
    b = s.put("sunday hamper picnic the pack for", "chat")  # near-dupe merge
    assert b == a and s.last_autospot is None
    c = s.put("pack the picnic hamper for sunday", "email")  # exact hit
    assert c == a and s.last_autospot is None


def test_bridge_opt_out_per_store_and_per_call():
    s = Store(auto_spot=False)
    s.put(RUNS_OLD, "user")
    s.put(RUNS_STOPPED, "user")
    assert s.last_autospot is None
    assert s.tombstoned() == [] and s.conflicts() == []

    s2 = Store()
    s2.put(RUNS_OLD, "user")
    s2.put(RUNS_STOPPED, "user", auto_spot=False)
    assert s2.last_autospot is None
    assert s2.tombstoned() == [] and s2.conflicts() == []


def test_tombstoned_rows_never_nominate():
    s = Store(auto_spot=False)
    old_id = s.put(OFFICE_OLD, "user", auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "user", auto_spot=False)
    s.tombstone(old_id, new_id, "supersede-agreed", "code")
    fresh = s.put("the office brass key hangs inside", "user")
    cands, _dropped = autospot.find_candidates(
        s, fresh, "the office brass key hangs inside", "local")
    assert old_id not in [c[0] for c in cands]


def test_offline_path_touches_no_network():
    s = Store()
    s.put(RUNS_OLD, "user")
    def _boom(req, timeout=None):
        raise AssertionError("offline bridge must not touch the network")
    with mock.patch("urllib.request.urlopen", _boom):
        s.put(RUNS_STOPPED, "user")
    assert len(s.conflicts()) == 1


def test_admit_store_runs_the_bridge():
    s = Store()
    gate = Gate(FakeJudge({RUNS_OLD: GateVote(0.9, 5, 0.0),
                           RUNS_STOPPED: GateVote(0.9, 5, 0.0)}))
    assert s.admit(RUNS_OLD, "chat", gate) == "STORE"
    assert s.admit(RUNS_STOPPED, "chat", gate) == "STORE"
    assert len(s.conflicts()) == 1
    assert isinstance(s.last_autospot, dict)
    assert s.last_autospot["checked"] == 1


def test_live_agreement_tombstones_with_stubbed_transport():
    s = Store(auto_spot=False)
    old_id = s.put(OFFICE_OLD, "t", auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "t", auto_spot=False)
    live_a, live_b = live_relation_pair(api_key="k")
    calls = []
    with _stub_live({"rel": "supersede", "rel_confirm": "supersede"},
                    calls):
        summary = autospot.run_after_put(
            s, new_id, OFFICE_MOVED, "local",
            live_pair=(live_a, live_b))
    assert len(calls) == 2  # two differently worded live questions
    assert summary["tombstoned"] == [old_id]
    assert s.get(old_id)[4] == new_id
    assert s.get(old_id)[6] == "auto-spot"


def test_live_disagreement_vetoes_despite_offline_agreement():
    s = Store(auto_spot=False)
    old_id = s.put(OFFICE_OLD, "t", auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "t", auto_spot=False)
    live_a, live_b = live_relation_pair(api_key="k")
    with _stub_live({"rel": "supersede", "rel_confirm": "coexist"}):
        summary = autospot.run_after_put(
            s, new_id, OFFICE_MOVED, "local",
            live_pair=(live_a, live_b))
    assert summary["checked"] == 1 and summary["tombstoned"] == []
    assert s.tombstoned() == []
    assert s.get(old_id)[4] is None


def test_live_rate_limit_halts_and_keeps_both_live():
    from uncluttered_memory.jev_client import JevRelationJudge
    s = Store(auto_spot=False)
    old_id = s.put(OFFICE_OLD, "t", auto_spot=False)
    extra_id = s.put("the office relocated to 3 Main St", "t",
                     auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "t", auto_spot=False)

    class _HaltedLive(JevRelationJudge):
        def relation(self, old_text, new_text):
            raise RateLimited("free window spent")

    limited = (_HaltedLive(variant="direct"),
               _HaltedLive(variant="slot"))
    summary = autospot.run_after_put(s, new_id, OFFICE_MOVED, "local",
                                    live_pair=limited)
    assert summary["halted"] is True
    assert summary["tombstoned"] == [] and s.tombstoned() == []
    assert {t for _, t, *_ in s.live()} == {
        OFFICE_OLD, "the office relocated to 3 Main St", OFFICE_MOVED}
    assert s.get(old_id)[7] is None
    assert len(summary["outcomes"]) == 2
    assert summary["outcomes"][0]["reason"] == "judge-rate-limited"
    assert summary["outcomes"][1]["reason"] == "judge-halted-skipped"
    assert {old_id, extra_id} == set(summary["kept"])


def test_transport_halt_stops_the_run_and_skips_the_rest():
    # Any judge halt stops live voting: a transport failure on the
    # first pair breaks the loop instead of hitting the failed
    # judge again, and the remainder is itemized as skipped.
    from uncluttered_memory.jev_client import JevError, JevRelationJudge
    s = Store(auto_spot=False)
    first_id = s.put(OFFICE_OLD, "t", auto_spot=False)
    second_id = s.put("the office relocated to 3 Main St", "t",
                      auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "t", auto_spot=False)

    class _FlakyLive(JevRelationJudge):
        def relation(self, old_text, new_text):
            raise JevError("transport blew up")

    flaky = (_FlakyLive(variant="direct"), _FlakyLive(variant="slot"))
    summary = autospot.run_after_put(s, new_id, OFFICE_MOVED, "local",
                                    live_pair=flaky)
    assert summary["halted"] is True and summary["checked"] == 0
    assert len(summary["outcomes"]) == 2
    assert summary["outcomes"][0]["reason"] == "judge-halted"
    assert summary["outcomes"][1]["reason"] == "judge-halted-skipped"
    assert {first_id, second_id} == set(summary["kept"])
    assert s.tombstoned() == [] and s.conflicts() == []
    assert {t for _, t, *_ in s.live()} == {
        OFFICE_OLD, "the office relocated to 3 Main St", OFFICE_MOVED}


def test_exhausted_rate_budget_stops_live_votes_without_network():
    s = Store(auto_spot=False)
    old_id = s.put(OFFICE_OLD, "t", auto_spot=False)
    new_id = s.put(OFFICE_MOVED, "t", auto_spot=False)
    live_a, live_b = live_relation_pair(api_key="k")
    spent = RateLimiter(calls_per_min=0, chars_per_min=0)
    def _boom(req, timeout=None):
        raise AssertionError("no live call may fire over budget")
    with mock.patch("urllib.request.urlopen", _boom):
        summary = autospot.run_after_put(
            s, new_id, OFFICE_MOVED, "local",
            live_pair=(live_a, live_b), rate_limiter=spent)
    assert summary["rate_limited"] is True
    assert summary["checked"] == 0
    assert len(summary["outcomes"]) == 1
    assert summary["outcomes"][0]["reason"] == "rate-budget-exhausted"
    assert summary["outcomes"][0]["applied"] is False
    assert summary["kept"] == [old_id]
    assert s.tombstoned() == [] and s.get(old_id)[4] is None


def test_offline_votes_spend_no_rate_budget():
    s = Store(auto_spot=False)
    s.put(RUNS_OLD, "t", auto_spot=False)
    new_id = s.put(RUNS_STOPPED, "t", auto_spot=False)
    limiter = RateLimiter()
    before = limiter.remaining()
    autospot.run_after_put(s, new_id, RUNS_STOPPED, "local",
                           rate_limiter=limiter)
    assert limiter.remaining() == before
    assert len(s.conflicts()) == 1


def test_server_shares_its_limiter_and_optional_live_pair():
    from uncluttered_memory.gate import RuleJudge
    s = Store()
    app = MemoryApp(s, RuleJudge())
    assert s.rate_limiter is app.limiter
    assert s.auto_live_pair is None
    keep = RateLimiter()
    s2 = Store()
    s2.rate_limiter = keep
    MemoryApp(s2, RuleJudge())
    assert s2.rate_limiter is keep
    live_a, live_b = live_relation_pair(api_key="k")
    s3 = Store()
    MemoryApp(s3, RuleJudge(), live_pair=(live_a, live_b))
    assert s3.auto_live_pair == (live_a, live_b)


def test_store_defaults_bridge_on_with_threshold_caps():
    assert inspect.signature(
        Store.__init__).parameters["auto_spot"].default is True
    sig = inspect.signature(Store.put)
    assert sig.parameters["auto_spot"].default is None
    assert sig.parameters["relation_pair"].default is None
    assert sig.parameters["live_pair"].default is None
    assert sig.parameters["rate_limiter"].default is None
    assert th.AUTOSPOT_MIN_JACCARD == 0.30
    assert th.AUTOSPOT_MAX_PAIRS_PER_WRITE == 5
    sig2 = inspect.signature(autospot.run_after_put)
    assert sig2.parameters["min_jaccard"].default == th.AUTOSPOT_MIN_JACCARD
    assert sig2.parameters["max_pairs"].default == (
        th.AUTOSPOT_MAX_PAIRS_PER_WRITE)
    sig3 = inspect.signature(autospot.find_candidates)
    assert sig3.parameters["max_pairs"].default == (
        th.AUTOSPOT_MAX_PAIRS_PER_WRITE)


def test_no_numeric_boundary_in_autospot_source():
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src"
           / "uncluttered_memory" / "autospot.py").read_text(
               encoding="utf-8")
    tree = ast.parse(src)
    floats = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            floats.add(node.value)
    assert floats <= {0.0, 1.0}, floats
    assert "th.AUTOSPOT_MIN_JACCARD" in src
    assert "th.AUTOSPOT_MAX_PAIRS_PER_WRITE" in src
