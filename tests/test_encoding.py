"""The report stream is forced to UTF-8 with a named error handler, and
the success line is pinned byte for byte.

Round-2 finding: the success line could be mangled when the console (or
a pipe) spoke cp1252. The runner now reconfigures stdout/stderr
explicitly (UTF-8, errors="backslashreplace") and these tests pin the
exact bytes, including under a cp1252-forced environment.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from uncluttered_memory.console import ERRORS, configure_console

ROOT = Path(__file__).resolve().parents[1]
SUCCESS_LINE = "PASS: golden 0 failures, bulk 0 failures"


def _run_eval(extra_env=None, args=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"  # the mangling scenario
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    env.pop("HERMES_CUSTOM_OPENCODE_AI_API_KEY", None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(ROOT / "eval" / "run.py")]
    if args:
        cmd += args
    return subprocess.run(cmd, capture_output=True, cwd=str(ROOT), env=env)


def test_success_line_exact_bytes_under_cp1252_console():
    proc = _run_eval()
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    # strict UTF-8 decode of the whole report proves no cp1252 round trip
    text = proc.stdout.decode("utf-8")
    assert text.splitlines()[-1] == SUCCESS_LINE
    assert proc.stdout.endswith((SUCCESS_LINE + "\n").encode("utf-8"))
    assert b"\xef\xbf\xbd" not in proc.stdout  # no replacement chars


def test_non_ascii_case_text_not_mangled_under_cp1252_console(tmp_path):
    case = {"id": "u1", "suite": "admit", "kind": "unicode",
            "provenance": "synthetic-rule",
            "text": "the trail marker \u2265 the gate", "expect": "STORE"}
    p = tmp_path / "uni.jsonl"
    p.write_text(json.dumps(case) + "\n", encoding="utf-8")
    proc = _run_eval(args=["--cases", str(p)])
    assert proc.returncode == 1  # the case is deliberately failing
    text = proc.stdout.decode("utf-8")
    assert "the trail marker \u2265 the gate" in text
    assert "\u2265".encode("utf-8") == b"\xe2\x89\xa5"
    assert b"\xe2\x89\xa5" in proc.stdout


def test_configure_console_forces_utf8_and_named_errors(monkeypatch):
    import io
    fake = io.TextIOWrapper(io.BytesIO(), encoding="cp1252",
                            errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    monkeypatch.setattr(sys, "stderr", fake)
    configure_console()
    assert fake.encoding.lower().replace("-", "") == "utf8"
    assert fake.errors == ERRORS == "backslashreplace"
    fake.write("caf\u00e9 \u2265")
    fake.flush()
    assert fake.buffer.getvalue().endswith(
        "caf\u00e9 \u2265".encode("utf-8"))
