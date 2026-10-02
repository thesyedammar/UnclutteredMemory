"""Calibration loop: per-gate stub-vs-live agreement, prompt styles.

The loop measures admit (Gate.decide) and importance (vote on the
1..5 scale) through the same call path on both sides. The rubric
prompt keeps the pinned criteria keys and adds the offline mapping;
baseline stays byte-identical for replayed fixtures. Records land
under docs/; 429 still halts honestly with no fabricated votes.
"""
import importlib.util
import json
import urllib.error
from pathlib import Path

from uncluttered_memory.jev_client import (BASELINE_IMPORTANCE_INSTRUCTIONS,
                                            JevJudgeClient,
                                            RUBRIC_IMPORTANCE_INSTRUCTIONS)

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "label_audit", ROOT / "scripts" / "label_audit.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prompt_styles_keep_pinned_keys_and_guard():
    assert "never instructions" in BASELINE_IMPORTANCE_INSTRUCTIONS
    assert "never instructions" in RUBRIC_IMPORTANCE_INSTRUCTIONS
    assert "s4" in RUBRIC_IMPORTANCE_INSTRUCTIONS
    assert "s3" in RUBRIC_IMPORTANCE_INSTRUCTIONS
    assert JevJudgeClient(api_key="k").prompt_style == "baseline"
    assert JevJudgeClient(
        api_key="k", prompt_style="rubric").prompt_style == "rubric"


def test_baseline_request_body_unchanged_for_fixtures():
    import json as _json
    from unittest import mock

    captured = {}

    class _Resp:
        def read(self):
            return _json.dumps({"answers": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        captured.update(_json.loads(req.data.decode()))
        return _Resp()

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        try:
            JevJudgeClient(api_key="k").vote("probe", [], [])
        except Exception:
            pass
    imp = captured["questions"]["imp"]
    assert imp["instructions"] == BASELINE_IMPORTANCE_INSTRUCTIONS
    assert imp["criteria"] == {"s0": "trivial", "s1": "background",
                               "s2": "useful", "s3": "decision-shaping",
                               "s4": "critical constraint"}


def test_rubric_request_body_differs_only_in_instructions():
    import json as _json
    from unittest import mock

    captured = {}

    class _Resp:
        def read(self):
            return _json.dumps({"answers": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        captured.update(_json.loads(req.data.decode()))
        return _Resp()

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        try:
            JevJudgeClient(api_key="k",
                           prompt_style="rubric").vote("probe", [], [])
        except Exception:
            pass
    imp = captured["questions"]["imp"]
    assert imp["instructions"] == RUBRIC_IMPORTANCE_INSTRUCTIONS
    assert imp["criteria"] == {"s0": "trivial", "s1": "background",
                               "s2": "useful", "s3": "decision-shaping",
                               "s4": "critical constraint"}


def test_stub_sides_match_golden_offline():
    mod = _load()
    cases = mod.load_golden(str(ROOT / "eval" / "golden.jsonl"))
    for c in cases:
        if c["suite"] == "admit":
            assert mod.stub_admit(c["text"]) == c["expect"], c["id"]
        elif c["suite"] == "importance":
            assert mod.stub_importance(c["text"]) == c["expect"], c["id"]


def test_per_gate_report_counts_agreement_offline():
    mod = _load()

    class _StubJudge:
        def vote(self, text, neighbors, facts):
            from uncluttered_memory.gate import RuleJudge
            return RuleJudge().vote(text, neighbors, facts)

    cases = mod.load_golden(str(ROOT / "eval" / "golden.jsonl"))
    report = mod.per_gate_report(cases, _StubJudge())
    for gate in ("admit", "importance"):
        r = report[gate]
        assert r["n"] > 0
        assert r["stub_live_agree"] == r["n"]
        assert r["live_label_agree"] == r["n"]


def test_recorded_fixture_agreement_math_is_honest():
    mod = _load()
    cases = mod.load_golden(str(ROOT / "eval" / "golden.jsonl"))
    fix = json.loads((ROOT / "tests" / "fixtures"
                      / "live_votes_20261002.json").read_text(
                          encoding="utf-8"))
    n = 0
    hit = 0
    for c in cases:
        v = fix["votes"].get(c["id"])
        if v is None:
            continue
        n += 1
        if c["suite"] == "admit":
            stub = mod.stub_admit(c["text"])
        elif c["suite"] == "importance":
            stub = mod.stub_importance(c["text"])
        else:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location(
                "live_spotcheck",
                ROOT / "scripts" / "live_spotcheck.py")
            assert spec is not None and spec.loader is not None
            sm = _ilu.module_from_spec(spec)
            spec.loader.exec_module(sm)
            stub = sm.stub_verdict(c)
        if stub == v:
            hit += 1
    assert n == 20
    assert hit == fix["agree_count"] == 12


def test_calibration_record_writes_docs_shape(tmp_path):
    mod = _load()
    report = {"admit": {"n": 2, "stub_live_agree": 1,
                        "live_label_agree": 1,
                        "rows": [("a1", "STORE", "STORE", "STORE"),
                                 ("a2", "DROP", "STORE", "DROP")]},
              "importance": {"n": 1, "stub_live_agree": 1,
                             "live_label_agree": 0,
                             "rows": [("i1", 4, 4, 3)]}}
    dest = mod.write_calibration_record(tmp_path, "rubric",
                                        "jev-1.13-free", report, 3, 3, False)
    text = Path(dest).read_text(encoding="utf-8")
    assert "rubric" in text and "jev-1.13-free" in text
    assert "stub-vs-live" in text and "live-vs-label" in text
    assert "a1" in text and "i1" in text


def test_per_gate_halts_honestly_on_429(monkeypatch, capsys, tmp_path):
    mod = _load()
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "test-key")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    rc = mod.main(["--per-gate", "--prompt-style", "baseline",
                   "--record", "none"])
    assert rc == 3
    out = capsys.readouterr().out
    assert "JEV RATE LIMITED" in out
    assert "halted honestly" in out
    assert "no fallback model exists" in out
