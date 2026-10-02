"""The live spotcheck never gates anything, skips cleanly offline, and
halts honestly on 429 with no fallback and no fabricated votes."""
import importlib.util
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

from eval.run import load_cases

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "live_spotcheck", ROOT / "scripts" / "live_spotcheck.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skips_cleanly_without_key():
    env = dict(os.environ)
    env.pop("HERMES_CUSTOM_OPENCODE_AI_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "live_spotcheck.py")],
        capture_output=True, env=env, cwd=str(ROOT))
    assert proc.returncode == 0
    out = proc.stdout.decode("utf-8")
    assert "skipped cleanly" in out
    assert "no live calls" in out


def test_sample_is_deterministic_and_covers_judged_suites():
    mod = _load()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    p1 = mod.sample_cases(cases, 20)
    p2 = mod.sample_cases(cases, 20)
    assert len(p1) == 20
    assert [c["id"] for c in p1] == [c["id"] for c in p2]
    assert all(c["suite"] in mod.JUDGED_SUITES for c in p1)
    assert {c["suite"] for c in p1} == set(mod.JUDGED_SUITES)


def test_halts_honestly_on_429(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "test-key")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr("urllib.request.urlopen", boom)
    rc = mod.main(["--n", "20"])
    assert rc == 3
    out = capsys.readouterr().out
    assert "JEV RATE LIMITED" in out
    assert "halted honestly" in out
    assert "no fallback model exists" in out
    assert "nothing was voted by any stub in place of Jev" in out


def test_stub_side_of_the_comparison_matches_the_claim():
    """The offline half of the spotcheck agrees with the golden labels."""
    mod = _load()
    cases = load_cases(ROOT / "eval" / "golden.jsonl")
    for c in mod.sample_cases(cases, 20):
        assert mod.stub_verdict(c) == c["expect"], c["id"]
