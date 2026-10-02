"""P4 playground test: the demo runs offline and prints every verdict."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "playground" / "demo.py"


def test_demo_runs_offline_with_all_verdicts():
    proc = subprocess.run([sys.executable, str(DEMO)], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "offline RuleJudge stub, not Jev" in out
    for marker in ("action=STORE", "action=DROP", "action=QUARANTINE",
                   "RECALL", "INJECT", "REVIEW", "STATUS live=2 "
                   "quarantined=1 error_count=0"):
        assert marker in out, marker
    assert "play>0.7" in out
    assert "sensitive>0.7" in out
    assert "uncertain-low-conf" in out
