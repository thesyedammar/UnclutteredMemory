#!/usr/bin/env python3
"""Label audit: golden importance cases against LIVE jev-1.13-free.

Runs every importance case in the golden set through the live
jev-1.13-free judge and prints live-vs-label agreement, one line per
case plus a summary. The live side reads through the same vote call
path as the offline side (judge.vote(text, [], []).importance on the
1..5 design scale), so a difference is a genuine verdict disagreement
on the shared scale, never a call-path artifact.

INFORMATION ONLY. The agreement rate gates nothing: no test, no eval
exit code, no CI depends on it. Without the API key the script skips
cleanly with no network calls. On HTTP 429 it halts honestly with the
rate-limit message; there is no fallback model and nothing is ever
voted by a stub in place of a live answer. The only model is
jev-1.13-free.

Exit codes: 0 completed or skipped (information only), 2 unreadable
golden set or rejected key, 3 halted on the Jev rate limit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval.run import GOLDEN_FILE  # noqa: E402
from uncluttered_memory.console import configure_console  # noqa: E402
from uncluttered_memory.jev_client import (BadKey, JevError,  # noqa: E402
                                           JevJudgeClient, RateLimited,
                                           rate_limited_message)


def load_importance(path) -> list:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [c for c in rows if c.get("suite") == "importance"]


def live_importance(judge, text: str) -> int:
    """One shared vote call path on the 1..5 design scale."""
    return judge.vote(text, [], []).importance


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(prog="label-audit")
    parser.add_argument("--golden", default=str(GOLDEN_FILE))
    args = parser.parse_args(argv)

    try:
        cases = load_importance(args.golden)
    except (OSError, ValueError) as e:
        print("label audit error: cannot read golden set %s (%s)"
              % (args.golden, e))
        return 2
    if not cases:
        print("label audit error: no importance cases in %s" % args.golden)
        return 2

    judge = JevJudgeClient()
    if not judge.api_key:
        print("label audit: skipped cleanly; %s is not set, so no live "
              "calls were made (information only, nothing gates on this)."
              % "HERMES_CUSTOM_OPENCODE_AI_API_KEY")
        return 0

    print("label audit: %d golden importance cases, model=%s (the only "
          "model in this project; no fallback exists)"
          % (len(cases), judge.model))
    print("live = jev-1.13-free vote; label = golden expect (1..5).")
    print("INFORMATION ONLY: the agreement rate below gates nothing.")

    agree = 0
    done = 0
    for case in sorted(cases, key=lambda c: c.get("id", "")):
        try:
            got = live_importance(judge, case["text"])
        except RateLimited as e:
            print("JEV RATE LIMITED: " + rate_limited_message(e))
            print("label audit halted honestly after %d of %d cases; "
                  "nothing was voted by any stub in place of Jev and no "
                  "fallback model exists." % (done, len(cases)))
            if done:
                print("PARTIAL live-vs-label agreement (information "
                      "only): %d/%d = %.1f%%"
                      % (agree, done, 100.0 * agree / done))
            return 3
        except BadKey as e:
            print("label audit error: %s" % e)
            return 2
        except JevError as e:
            print("label audit halted: %s" % e)
            return 2
        done += 1
        same = got == case["expect"]
        agree += 1 if same else 0
        print("%-16s live=%-4r label=%-4r %s"
              % (case.get("id", "?"), got, case["expect"],
                 "agree" if same else "differ"))
    print("live-vs-label agreement (INFORMATION ONLY, never a gate): "
          "%d/%d = %.1f%%" % (agree, done, 100.0 * agree / done))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
