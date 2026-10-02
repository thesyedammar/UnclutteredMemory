#!/usr/bin/env python3
"""Live spot-check: a small golden sample against jev-1.13-free.

Samples 20 golden cases (deterministic, spread across the judge-involved
suites), asks the live judge the same question the offline stub answers,
and prints the stub-vs-live agreement rate.

INFORMATION ONLY. The agreement rate gates nothing: no test, no eval
exit code, no CI depends on it. Without the API key the script skips
cleanly with no network calls. On HTTP 429 it halts honestly with the
rate-limit message; there is no fallback model and nothing is ever
fabricated from a stub in place of a live answer.

Relation cases cost two live calls each (one per judge slot of the
two-judge decide()).

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
                                           JevRelationJudge,
                                           RateLimited,
                                           offline_relation_pair,
                                           rate_limited_message)

#: Only suites where a judge votes; dedupe and rerank are pure code.
JUDGED_SUITES = ("admit", "importance", "contradict", "supersede")


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


def stub_verdict(case: dict):
    suite = case["suite"]
    if suite == "admit":
        return Gate(RuleJudge()).decide(case["text"], [], []).action
    if suite == "importance":
        return RuleJudge().vote(case["text"], [], []).importance
    if suite in ("contradict", "supersede"):
        return supmod.decide(case["old"], case["new"],
                             *offline_relation_pair()).action
    raise ValueError("no offline verdict for suite %r" % suite)


def live_verdict(case: dict, gate_judge, relation_judge):
    suite = case["suite"]
    if suite == "admit":
        return Gate(gate_judge).decide(case["text"], [], []).action
    if suite == "importance":
        return gate_judge.vote(case["text"], [], []).importance
    if suite in ("contradict", "supersede"):
        # Two live calls: decide() asks both judge slots.
        return supmod.decide(case["old"], case["new"],
                             relation_judge, relation_judge).action
    raise ValueError("no live verdict for suite %r" % suite)


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(prog="live-spotcheck")
    parser.add_argument("--golden", default=str(GOLDEN_FILE))
    parser.add_argument("--n", type=int, default=20)
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
          "jev-1.13-free. Relation cases cost two live calls each.")
    print("INFORMATION ONLY: the agreement rate below gates nothing.")

    relation_judge = JevRelationJudge()
    agree = 0
    done = 0
    for case in picks:
        try:
            stub = stub_verdict(case)
            live = live_verdict(case, gate_judge, relation_judge)
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
        same = stub == live
        agree += 1 if same else 0
        print("%-10s %-16s stub=%-11r live=%-11r %s"
              % (case["suite"], case["id"], stub, live,
                 "agree" if same else "differ"))

    if done:
        print("stub-vs-live agreement (INFORMATION ONLY, never a gate): "
              "%d/%d = %.1f%%" % (agree, done, 100.0 * agree / done))
    else:
        print("no cases were run; nothing to compare")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
