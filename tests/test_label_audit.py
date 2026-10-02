"""The label audit never gates anything, skips cleanly offline, and
halts honestly on 429 with no fallback and no fabricated votes."""
import importlib.util
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "label_audit", ROOT / "scripts" / "label_audit.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skips_cleanly_without_key():
    env = dict(os.environ)
    env.pop("HERMES_CUSTOM_OPENCODE_AI_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "label_audit.py")],
        capture_output=True, env=env, cwd=str(ROOT))
    assert proc.returncode == 0
    out = proc.stdout.decode("utf-8")
    assert "skipped cleanly" in out
    assert "no live calls" in out


def test_loads_only_importance_cases():
    mod = _load()
    cases = mod.load_importance(ROOT / "eval" / "golden.jsonl")
    assert len(cases) > 0
    assert all(c["suite"] == "importance" for c in cases)
    assert all(1 <= c["expect"] <= 5 for c in cases)


def test_unreadable_golden_is_exit_2(tmp_path):
    mod = _load()
    assert mod.main(["--golden", str(tmp_path / "gone.jsonl")]) == 2


def test_halts_honestly_on_429(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setenv("HERMES_CUSTOM_OPENCODE_AI_API_KEY", "test-key")

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr("urllib.request.urlopen", boom)
    rc = mod.main([])
    assert rc == 3
    out = capsys.readouterr().out
    assert "JEV RATE LIMITED" in out
    assert "halted honestly" in out
    assert "no fallback model exists" in out
    assert "nothing was voted by any stub in place of Jev" in out
