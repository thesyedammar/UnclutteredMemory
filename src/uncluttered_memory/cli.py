"""Unclutter CLI: run the frozen eval, tune on the train split only,
and apply named-human overrides (restore / retire / tombstone)."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from uncluttered_memory import calibrate as calmod
from uncluttered_memory import supersede as supmod
from uncluttered_memory.console import configure_console
from uncluttered_memory.gate import RuleJudge
from uncluttered_memory.store import Store

REPO = Path(__file__).resolve().parents[2]
EVAL_RUN = REPO / "eval" / "run.py"


def _eval():
    spec = importlib.util.spec_from_file_location("unclutter_eval_run", EVAL_RUN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def do_calibrate(task: str, out) -> int:
    mod = _eval()
    cases = mod.load_cases(mod.CASES_FILE)
    train, test = mod.split_cases(cases)
    train_admit = [c for c in train if c.get("suite") == "admit"]
    test_admit = [c for c in test if c.get("suite") == "admit"]
    judge = RuleJudge()
    out = out or str(REPO / "thresholds" / (task + ".json"))
    reg = calmod.calibrate_gate(
        train_admit, task, out,
        lambda c: judge.vote(c["text"], [], []).durable)
    print("wrote %s task=%s admit.durable=%.2f train_n=%d train_f1=%.3f"
          " (test split untouched, n=%d)" %
          (out, task, reg["report"]["threshold"], len(train_admit),
           reg["report"]["f1"], len(test_admit)))
    return 0


def do_override(args) -> int:
    """Named-human override against a store file. All actions documented."""
    db = Path(args.db)
    if str(db.parent) not in ("", "."):
        db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(db))
    if store.get(args.fact_id) is None:
        print("override refused: no fact %d in %s" % (args.fact_id, db))
        return 2
    try:
        supmod.human_override(store, args.fact_id, args.action,
                              actor="human", target_id=args.target_id,
                              reason=args.reason)
    except ValueError as e:
        print("override refused: %s" % e)
        return 2
    if args.action == "restore":
        print("override: fact %d restore by human (live again)"
              % args.fact_id)
    else:
        print("override: fact %d %s -> %d by human (reason=%r)"
              % (args.fact_id, args.action, args.target_id,
                 args.reason or ("human-" + args.action)))
    return 0


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(prog="unclutter", description="UnclutteredMemory CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="run the frozen eval")
    p_run.add_argument("--registry", default=None)
    p_run.add_argument("--task", default="general-qa")
    p_cal = sub.add_parser("calibrate", help="tune thresholds on train split only")
    p_cal.add_argument("--task", default="general-qa")
    p_cal.add_argument("--out", default=None)
    p_ov = sub.add_parser(
        "override",
        help="named-human fact override: restore | retire | tombstone")
    p_ov.add_argument("--db", default="uncluttered.db",
                      help="SQLite store path (default: ./uncluttered.db)")
    p_ov.add_argument("--fact-id", type=int, required=True,
                      help="id of the fact to act on")
    p_ov.add_argument(
        "--action", required=True, choices=("restore", "retire", "tombstone"),
        help="restore: clear the tombstone fields and go live again; "
             "retire: soft-tombstone the fact toward --target-id; "
             "tombstone: explicit alias of retire, same soft tombstone "
             "with actor human")
    p_ov.add_argument("--target-id", type=int, default=None,
                      help="replacement fact id; required by retire and "
                           "tombstone")
    p_ov.add_argument("--reason", default="",
                      help="free-text reason recorded on the tombstone")
    sub.add_parser("redteam", help="fire the poison gauntlet (P2)")
    sub.add_parser("gauntlet", help="record the gauntlet demo (P7)")
    args = parser.parse_args(argv)
    if args.command == "run":
        argv = ["--task", args.task]
        if args.registry:
            argv += ["--registry", args.registry]
        return _eval().main(argv)
    if args.command == "calibrate":
        return do_calibrate(args.task, args.out)
    if args.command == "override":
        return do_override(args)
    print("unclutter %s: not built until its phase" % args.command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
