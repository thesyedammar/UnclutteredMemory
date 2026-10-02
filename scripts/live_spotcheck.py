#!/usr/bin/env python3
"""Live spot-check: a small golden sample against jev-1.13-free.

Samples 20 golden cases (deterministic, spread across the judge-involved
suites), asks the live judges, and prints the stub-vs-live agreement rate.

Relation independence: each relation case asks TWO differently worded
live Jev questions (a direct phrasing plus a slot phrasing with
different instructions and different criteria labels; see jev_client
live_relation_pair) and also asks the offline heterogeneous pair
(Strict plus Lenient). A destructive live verdict (TOMBSTONE or
CONFLICT) proceeds only when the live pair agrees with each other AND
the offline pair agrees with each other AND both agreed relations
match; any disagreement vetoes to KEEP. Asking one identical live
question twice is rejected by construction (live_confirmed_decide
raises ValueError when the two live questions match).

INFORMATION ONLY. The agreement rate gates nothing: no test, no eval
exit code, no CI depends on it. Without the API key the script skips
cleanly with no network calls. On full completion with the key
present the script refreshes tests/fixtures/live_votes_20261002.json
(recorded live votes plus metadata), which the offline ratchet test
in tests/test_live_ratchet.py reads; --no-record (or --record none)
disables the refresh for dry runs with non-live judges. On HTTP 429
it halts honestly with the rate-limit message; there is no fallback
model and nothing is ever fabricated from a stub in place of a live answer.

Relation cases cost two live calls each (one per live question) plus
offline strict plus lenient confirmation, which costs no calls.

Importance cases compare the stub vote against the live
jev-1.13-free vote on the shared 1..5 design scale, through the same
vote call path on both sides (see importance_verdict). The
comparison is INFORMATION ONLY, exactly like the rest of this
script: agreement or disagreement gates nothing.

Exit codes: 0 completed or skipped (information only), 2 unreadable
golden set or rejected key, 3 halted on the Jev rate limit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval.run import GOLDEN_FILE, load_cases  # noqa: E402
from uncluttered_memory import supersede as supmod  # noqa: E402
from uncluttered_memory.console import configure_console  # noqa: E402
from uncluttered_memory.gate import Gate, RuleJudge  # noqa: E402
from uncluttered_memory.jev_client import (BadKey, JevError,  # noqa: E402
                                           JevJudgeClient,
                                           RateLimited,
                                           live_confirmed_decide,
                                           live_relation_pair,
                                           offline_relation_pair,
                                           rate_limited_message)

#: Only suites where a judge votes; dedupe and rerank are pure code.
JUDGED_SUITES = ("admit", "importance", "contradict", "supersede")

#: Checked-in record of the live run, refreshed by this script on
#: every full completion when the API key is present. Pass
#: --no-record for dry runs with non-live judges (a fake judge must
#: never overwrite recorded live votes). Read offline by
#: tests/test_live_ratchet.py, which fails when stub-vs-live
#: agreement drops below the floor.
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "live_votes_20261002.json"


def record_fixture(picks: list, live_by_id: dict, path=None):
    """Write per-case live votes plus run metadata as JSON."""
    import datetime
    import json
    dest = Path(path) if path else FIXTURE_PATH
    agree = sum(1 for c in picks
                if live_by_id.get(c["id"]) == stub_verdict(c))
    total = len(picks)
    payload = {
        "agreement": "%d/%d = %.1f%%" % (
            agree, total, 100.0 * agree / total if total else 0.0),
        "agree_count": agree,
        "date": datetime.date.today().isoformat(),
        "floor_note": ("ratchet floor 0.35 is the recorded "
                       "importance-audit 0.417 minus margin"),
        "method": ("deterministic 20-case spread over judged suites "
                   "(admit, importance, contradict, supersede); stub = "
                   "offline RuleJudge/strict+lenient pair, live = "
                   "jev-1.13-free with paired live questions plus "
                   "offline confirmation on relation cases"),
        "model": "jev-1.13-free",
        "sample": ("fixed 20-case spotcheck (see sample_cases in "
                   "scripts/live_spotcheck.py, n=20)"),
        "source": ("real live runs; refreshed by "
                   "scripts/live_spotcheck.py on full completion when "
                   "the API key is present"),
        "total": total,
        "votes": {c["id"]: live_by_id[c["id"]] for c in picks},
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")
    return dest


def sample_cases(cases: list, n: int = 20) -> list:
    """Deterministic spread of judged-suite cases, ordered by id."""
    pool = sorted((c for c in cases if c["suite"] in JUDGED_SUITES),
                  key=lambda c: c["id"])
    if not pool:
        return []
    step = max(1, len(pool) // n)
    picks = pool[::step][:n]
    if len(picks) < n:
        for c in pool:
            if c not in picks:
                picks.append(c)
            if len(picks) == n:
                break
    return picks[:n]


def importance_verdict(judge, text: str) -> int:
    """One shared vote call path for the importance comparison.

    Both the stub side (RuleJudge) and the live side (jev-1.13-free
    client) are read through judge.vote(text, [], []).importance on
    the 1..5 design scale, so a stub/live difference is a genuine
    verdict disagreement on the same scale, never a call-path or
    scale artifact.
    """
    return judge.vote(text, [], []).importance


def stub_verdict(case: dict):
    suite = case["suite"]
    if suite == "admit":
        return Gate(RuleJudge()).decide(case["text"], [], []).action
    if suite == "importance":
        return importance_verdict(RuleJudge(), case["text"])
    if suite in ("contradict", "supersede"):
        return supmod.decide(case["old"], case["new"],
                             *offline_relation_pair()).action
    raise ValueError("no offline verdict for suite %r" % suite)


def live_verdict(case: dict, gate_judge, live_a, live_b,
                 offline_a=None, offline_b=None):
    suite = case["suite"]
    if suite == "admit":
        return Gate(gate_judge).decide(case["text"], [], []).action
    if suite == "importance":
        return importance_verdict(gate_judge, case["text"])
    if suite in ("contradict", "supersede"):
        # Independent evidence: two differently worded live Jev
        # questions must agree with each other AND the offline
        # heterogeneous pair (Strict plus Lenient) must agree on the
        # same pair; any disagreement vetoes to KEEP. A single live
        # question passed twice raises ValueError by construction.
        if offline_a is None or offline_b is None:
            offline_a, offline_b = offline_relation_pair()
        return live_confirmed_decide(case["old"], case["new"],
                                     live_a, live_b,
                                     offline_a, offline_b).action
    raise ValueError("no live verdict for suite %r" % suite)


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(prog="live-spotcheck")
    parser.add_argument("--golden", default=str(GOLDEN_FILE))
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--record", default=str(FIXTURE_PATH),
                        help="fixture refreshed on full completion; "
                        "'none' disables the refresh")
    parser.add_argument("--no-record", action="store_true",
                        help="dry run: never touch the fixture "
                        "(use with non-live judges)")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.golden)
    except (OSError, ValueError) as e:
        print("spotcheck error: cannot read golden set %s (%s)"
              % (args.golden, e))
        return 2
    picks = sample_cases(cases, args.n)

    gate_judge = JevJudgeClient()
    if not gate_judge.api_key:
        print("live spotcheck: skipped cleanly; %s is not set, so no live "
              "calls were made (information only, nothing gates on this)."
              % "HERMES_CUSTOM_OPENCODE_AI_API_KEY")
        return 0

    print("live spotcheck: %d golden cases sampled, model=%s (the only "
          "model in this project; no fallback exists)"
          % (len(picks), gate_judge.model))
    print("stub = offline RuleJudge/strict+lenient pair; live = "
          "jev-1.13-free. Relation cases cost two live calls each (two "
          "differently worded questions) plus offline confirmation.")
    print("INFORMATION ONLY: the agreement rate below gates nothing.")

    live_a, live_b = live_relation_pair()
    agree = 0
    done = 0
    live_by_id: dict = {}
    by_suite: dict = {}
    for case in picks:
        try:
            stub = stub_verdict(case)
            live = live_verdict(case, gate_judge, live_a, live_b)
        except RateLimited as e:
            print("JEV RATE LIMITED: " + rate_limited_message(e))
            print("spotcheck halted honestly after %d of %d cases; nothing "
                  "was voted by any stub in place of Jev and no fallback "
                  "model exists." % (done, len(picks)))
            if done:
                print("PARTIAL agreement (information only): %d/%d = %.1f%%"
                      % (agree, done, 100.0 * agree / done))
            return 3
        except BadKey as e:
            print("spotcheck error: %s" % e)
            return 2
        except JevError as e:
            print("spotcheck halted: %s" % e)
            return 2
        done += 1
        live_by_id[case["id"]] = live
        same = stub == live
        agree += 1 if same else 0
        slot = by_suite.setdefault(case["suite"], [0, 0])
        slot[1] += 1
        slot[0] += 1 if same else 0
        print("%-10s %-16s stub=%-11r live=%-11r %s"
              % (case["suite"], case["id"], stub, live,
                 "agree" if same else "differ"))

    if done:
        print("stub-vs-live agreement (INFORMATION ONLY, never a gate): "
              "%d/%d = %.1f%%" % (agree, done, 100.0 * agree / done))
        for suite in sorted(by_suite):
            hit, total = by_suite[suite]
            print("  %-10s agreement (information only): %d/%d %s"
                  % (suite, hit, total,
                     "agree" if hit == total else "differ present"))
        if picks and done == len(picks) and (
                not args.no_record
                and args.record.lower() != "none"):
            try:
                dest = record_fixture(picks, live_by_id, args.record)
            except OSError as e:
                print("fixture not refreshed: cannot write %s (%s)"
                      % (args.record, e))
            else:
                print("fixture refreshed: %s (stub-vs-live agreement "
                      "%d/%d)" % (dest, agree, done))
    else:
        print("no cases were run; nothing to compare")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
