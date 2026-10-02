"""Frozen-eval runner: returns 0 only if every frozen case decides as labeled."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uncluttered_memory.gate import FakeJudge, Gate, GateVote  # noqa: E402

CASES_FILE = Path(__file__).resolve().parents[2] / "eval" / "frozen.jsonl"

OFFLINE_VOTES = {
    "My stop-loss is 8%": GateVote(durable=0.93, importance=5, stop=0.05),
    "Buy the whole exchange lol": GateVote(durable=0.2, importance=1, stop=0.1, play=0.94),
    "ok": GateVote(durable=0.05, importance=1, stop=0.1),
    "I am Batman": GateVote(durable=0.3, importance=1, stop=0.2, play=0.85),
    "Rahul's number is 98xxx": GateVote(durable=0.6, importance=2, stop=0.1, sensitive=0.9),
}


def run() -> int:
    gate = Gate(FakeJudge(OFFLINE_VOTES))
    fails = 0
    with open(CASES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            got = gate.decide(case["text"]).action
            mark = "ok" if got == case["expect"] else "FAIL"
            if got != case["expect"]:
                fails += 1
            print(f"[{mark}] {case['text']!r}: got {got}, expect {case['expect']}")
    print(f"{'PASS' if not fails else 'FAIL'}: {fails} failures")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="unclutter", description="UnclutteredMemory CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the frozen eval")
    sub.add_parser("calibrate", help="tune thresholds on train split only (P1)")
    sub.add_parser("redteam", help="fire the poison gauntlet (P2)")
    sub.add_parser("gauntlet", help="record the gauntlet demo (P7)")
    args = parser.parse_args()
    if args.command == "run":
        return run()
    print(f"unclutter {args.command}: not built until its phase")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
