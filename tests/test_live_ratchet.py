"""Live-vs-stub agreement ratchet: live drift is a failing test.

The recorded live votes in tests/fixtures/live_votes_20261002.json
come from real jev-1.13-free runs on 2026-10-02 over the fixed 20-case
spotcheck sample. This suite recomputes the offline stub side and
checks the agreement against the recording, fully offline.

The floor is 0.35: the recorded importance-audit agreement of 0.417
(10/24, docs/label-audit-20261002.md) minus margin. A stub change
that tanks live agreement trips this ratchet loudly instead of
becoming a footnote.
"""
import importlib.util
import json
from pathlib import Path

from eval.run import load_cases

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "live_votes_20261002.json"

#: Documented floor: measured importance-audit 0.417 minus margin.
LIVE_AGREEMENT_FLOOR = 0.35


def _load_spotcheck():
    spec = importlib.util.spec_from_file_location(
        "live_spotcheck", ROOT / "scripts" / "live_spotcheck.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _agreement(mod, picks: list, votes: dict) -> tuple:
    hit = sum(1 for c in picks
              if votes.get(c["id"]) == mod.stub_verdict(c))
    return hit, len(picks)


def test_fixture_matches_the_fixed_spotcheck_sample():
    mod = _load_spotcheck()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    picks = mod.sample_cases(cases, 20)
    fix = _fixture()
    assert fix["model"] == "jev-1.13-free"
    assert fix["total"] == 20
    assert list(fix["votes"]) == [c["id"] for c in picks]


def test_recorded_agreement_is_honest():
    mod = _load_spotcheck()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    picks = mod.sample_cases(cases, 20)
    fix = _fixture()
    hit, total = _agreement(mod, picks, fix["votes"])
    assert fix["agree_count"] == hit
    assert fix["agreement"].startswith("%d/%d" % (hit, total))


def test_stub_vs_live_agreement_holds_the_floor():
    """Ratchet: agreement below 0.35 fails loudly (live drift)."""
    mod = _load_spotcheck()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    picks = mod.sample_cases(cases, 20)
    fix = _fixture()
    hit, total = _agreement(mod, picks, fix["votes"])
    rate = hit / total if total else 0.0
    assert rate >= LIVE_AGREEMENT_FLOOR, (
        "LIVE DRIFT: stub-vs-live agreement %d/%d = %.3f is below "
        "the floor %.2f (recorded %s on %s). Either the stub moved "
        "away from live Jev or the fixture is stale; refresh it with "
        "scripts/live_spotcheck.py and investigate before touching "
        "any golden label (labels are frozen, see "
        "eval/GOLDEN_CHANGELOG.md)."
        % (hit, total, rate, LIVE_AGREEMENT_FLOOR,
           fix.get("agreement"), fix.get("date")))


def test_record_fixture_writes_shape_offline(tmp_path):
    mod = _load_spotcheck()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    picks = mod.sample_cases(cases, 20)[:4]
    live_by_id = {c["id"]: c["expect"] for c in picks}
    dest = mod.record_fixture(picks, live_by_id, tmp_path / "v.json")
    with open(dest, encoding="utf-8") as f:
        payload = json.load(f)
    assert payload["total"] == 4
    assert payload["agree_count"] == 4
    assert payload["agreement"].startswith("4/4")
    assert payload["model"] == "jev-1.13-free"
    assert set(payload["votes"]) == {c["id"] for c in picks}
