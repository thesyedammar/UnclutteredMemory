#!/usr/bin/env python3
"""Label audit: golden importance cases against LIVE jev-1.13-free.

Runs every importance case in the golden set through the live
jev-1.13-free judge and prints live-vs-label agreement, one line per
case plus a summary. The live side reads through the same vote call
path as the offline side (judge.vote(text, [], []).importance on the
1..5 design scale), so a difference is a genuine verdict disagreement
on the shared scale, never a call-path artifact.

P2 calibration loop (--per-gate): the same script measures
stub-vs-live agreement per gate (admit via Gate.decide, importance
via vote.importance) over the golden set, under two prompt styles
(baseline and rubric, see jev_client.PROMPT_STYLES). The rubric style
adds the offline importance rubric to the live importance question so
the live rater reads the mapping the golden labels were written
against. The stub scoring is NOT tuned here: it is pinned by the
frozen golden labels (eval/GOLDEN_CHANGELOG.md), so calibration tunes
the live prompts only. Every calibration run writes a record under
docs/ unless --record none is passed.

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
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from eval.run import GOLDEN_FILE  # noqa: E402
from uncluttered_memory.console import configure_console  # noqa: E402
from uncluttered_memory.gate import Gate, RuleJudge  # noqa: E402
from uncluttered_memory.jev_client import (BadKey, JevError,  # noqa: E402
                                           JevJudgeClient, RateLimited,
                                           rate_limited_message)

CALIBRATION_GATES = ("admit", "importance")


def load_importance(path) -> list:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [c for c in rows if c.get("suite") == "importance"]


def load_golden(path) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def live_importance(judge, text: str) -> int:
    """One shared vote call path on the 1..5 design scale."""
    return judge.vote(text, [], []).importance


def stub_importance(text: str) -> int:
    """Offline side of the shared call path (RuleJudge, not Jev)."""
    return RuleJudge().vote(text, [], []).importance


def stub_admit(text: str) -> str:
    """Offline admit verdict through the real gate."""
    return Gate(RuleJudge()).decide(text, [], []).action


def live_admit(judge, text: str) -> str:
    """Live admit verdict through the same gate with a live judge."""
    return Gate(judge).decide(text, [], []).action


def per_gate_report(cases: list, live_judge) -> dict:
    """Stub-vs-live and live-vs-label agreement per gate, offline stub side.

    Returns {gate: {n, stub_live_agree, live_label_agree, rows}} where
    rows are (case_id, stub, live, label). Raises RateLimited, BadKey,
    or JevError from the live calls; callers halt honestly.
    """
    out: dict = {}
    for gate in CALIBRATION_GATES:
        pool = sorted((c for c in cases if c.get("suite") == gate),
                      key=lambda c: c.get("id", ""))
        rows = []
        for case in pool:
            if gate == "admit":
                stub = stub_admit(case["text"])
                live = live_admit(live_judge, case["text"])
            else:
                stub = stub_importance(case["text"])
                live = live_importance(live_judge, case["text"])
            rows.append((case.get("id", "?"), stub, live, case["expect"]))
        out[gate] = {
            "n": len(rows),
            "stub_live_agree": sum(1 for _, s, lv, _ in rows if s == lv),
            "live_label_agree": sum(1 for _, _, lv, e in rows if lv == e),
            "rows": rows,
        }
    return out


def format_gate_table(report: dict) -> list:
    lines = []
    for gate in CALIBRATION_GATES:
        r = report[gate]
        n = r["n"]
        sl = r["stub_live_agree"]
        ll = r["live_label_agree"]
        lines.append(
            "%-10s stub-vs-live %d/%d = %.1f%%; live-vs-label %d/%d = %.1f%%"
            % (gate, sl, n, 100.0 * sl / n if n else 0.0,
               ll, n, 100.0 * ll / n if n else 0.0))
    return lines


def write_calibration_record(dest: Path, style: str, model: str,
                             report: dict, done: int, total: int,
                             halted: bool) -> Path:
    """Write one docs/ calibration record. Returns the path written."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = Path(dest)
    if dest.is_dir() or str(dest).endswith("/"):
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / ("calibration-%s-%s.md" % (stamp, style))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Calibration %s (%s, %s)" % (stamp, style, model),
        "",
        "Prompt style: %s. Model: %s (only model, no fallback)." % (style, model),
        "Stub scoring is pinned by the frozen golden labels; calibration",
        "tunes the live prompts only (see eval/GOLDEN_CHANGELOG.md).",
        "INFORMATION ONLY: agreement rates gate nothing.",
        "",
    ]
    if halted:
        lines.append("Run halted honestly on the Jev rate limit after "
                     "%d of %d cases; partial numbers below." % (done, total))
        lines.append("")
    for line in format_gate_table(report):
        lines.append("- " + line)
    for gate in CALIBRATION_GATES:
        r = report[gate]
        lines.append("")
        lines.append("## %s per-case (stub vs live vs label)" % gate)
        for cid, stub, live, label in r["rows"]:
            mark = "agree" if stub == live else "differ"
            lines.append("- %s stub=%r live=%r label=%r %s"
                         % (cid, stub, live, label, mark))
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def run_calibration(args) -> int:
    try:
        cases = load_golden(args.golden)
    except (OSError, ValueError) as e:
        print("label audit error: cannot read golden set %s (%s)"
              % (args.golden, e))
        return 2
    if not [c for c in cases if c.get("suite") in CALIBRATION_GATES]:
        print("label audit error: no admit/importance cases in %s" % args.golden)
        return 2
    styles = ["baseline", "rubric"] if args.prompt_style == "both" else [args.prompt_style]
    for style in styles:
        judge = JevJudgeClient(prompt_style=style)
        if not judge.api_key:
            print("label audit: skipped cleanly; %s is not set, so no live "
                  "calls were made (information only, nothing gates on this)."
                  % "HERMES_CUSTOM_OPENCODE_AI_API_KEY")
            return 0
        print("calibration: prompt_style=%s model=%s (the only model; "
              "no fallback exists)" % (style, judge.model))
        print("stub = offline RuleJudge; live = jev-1.13-free. "
              "INFORMATION ONLY: agreement gates nothing.")
        total = sum(1 for c in cases if c.get("suite") in CALIBRATION_GATES)
        done = 0
        report: dict = {g: {"n": 0, "stub_live_agree": 0,
                            "live_label_agree": 0, "rows": []}
                        for g in CALIBRATION_GATES}
        halted = False
        try:
            for gate in CALIBRATION_GATES:
                pool = sorted((c for c in cases if c.get("suite") == gate),
                              key=lambda c: c.get("id", ""))
                for case in pool:
                    if gate == "admit":
                        stub = stub_admit(case["text"])
                        live = live_admit(judge, case["text"])
                    else:
                        stub = stub_importance(case["text"])
                        live = live_importance(judge, case["text"])
                    done += 1
                    r = report[gate]
                    r["n"] += 1
                    r["rows"].append((case.get("id", "?"), stub, live,
                                      case["expect"]))
                    if stub == live:
                        r["stub_live_agree"] += 1
                    if live == case["expect"]:
                        r["live_label_agree"] += 1
                    print("%-10s %-16s stub=%-6r live=%-6r label=%-6r %s"
                          % (gate, case.get("id", "?"), stub, live,
                             case["expect"],
                             "agree" if stub == live else "differ"))
        except RateLimited as e:
            print("JEV RATE LIMITED: " + rate_limited_message(e))
            print("calibration halted honestly after %d of %d cases; "
                  "nothing was voted by any stub in place of Jev and no "
                  "fallback model exists." % (done, total))
            halted = True
            for line in format_gate_table(report):
                print("PARTIAL " + line)
            if args.record.lower() != "none":
                dest = write_calibration_record(Path(args.record), style,
                                                judge.model, report,
                                                done, total, True)
                print("partial calibration record: %s" % dest)
            return 3
        except BadKey as e:
            print("label audit error: %s" % e)
            return 2
        except JevError as e:
            print("label audit halted: %s" % e)
            return 2
        for line in format_gate_table(report):
            print(line + " (INFORMATION ONLY, never a gate)")
        if args.record.lower() != "none":
            dest = write_calibration_record(Path(args.record), style,
                                            judge.model, report,
                                            done, total, False)
            print("calibration record: %s" % dest)
    return 0


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(prog="label-audit")
    parser.add_argument("--golden", default=str(GOLDEN_FILE))
    parser.add_argument("--per-gate", action="store_true",
                        help="calibration loop: stub-vs-live per gate "
                        "(admit, importance) with prompt styles")
    parser.add_argument("--prompt-style",
                        choices=("baseline", "rubric", "both"),
                        default="baseline",
                        help="live prompt wording; both runs baseline then "
                        "rubric (default: baseline)")
    parser.add_argument("--record", default="none",
                        help="where to write the docs/ calibration record "
                        "in --per-gate mode (a directory or file path); "
                        "'none' disables the record")
    args = parser.parse_args(argv)

    if args.per_gate:
        return run_calibration(args)

    try:
        cases = load_importance(args.golden)
    except (OSError, ValueError) as e:
        print("label audit error: cannot read golden set %s (%s)"
              % (args.golden, e))
        return 2
    if not cases:
        print("label audit error: no importance cases in %s" % args.golden)
        return 2

    judge = JevJudgeClient(prompt_style=args.prompt_style
                           if args.prompt_style in ("baseline", "rubric")
                           else "baseline")
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
