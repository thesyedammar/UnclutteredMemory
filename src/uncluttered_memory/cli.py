"""Unclutter CLI: run the frozen eval, tune on the train split only,
apply named-human overrides (restore / retire / tombstone), and
review the quarantine queue (review / approve / deny)."""
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


def do_conformal(task: str, out, gate: str = "admit",
                 target: float = calmod.CONFORMAL_TARGET_COVERAGE) -> int:
    """Tune one per-gate min_conf cutoff on the train split only."""
    mod = _eval()
    cases = mod.load_cases(mod.CASES_FILE)
    train, test = mod.split_cases(cases)
    pool = [c for c in train if c.get("suite") == gate]
    if gate == "admit":
        judge = RuleJudge()

        def _get_conf(c):
            return judge.vote(c["text"], [], []).conf

        def _is_correct(c):
            from uncluttered_memory.gate import Gate as _Gate
            got = _Gate(judge).decide(c["text"], [], []).action
            return got == c["expect"]
    elif gate == "importance":
        judge = RuleJudge()

        def _get_conf(c):
            return judge.vote(c["text"], [], []).conf

        def _is_correct(c):
            return judge.vote(c["text"], [], []).importance == c["expect"]
    else:
        print("conformal error: gate must be admit or importance")
        return 2
    out = out or str(REPO / "thresholds" / (task + ".json"))
    reg = calmod.calibrate_confidence(pool, task, out, _get_conf,
                                      _is_correct,
                                      target_coverage=target, gate=gate)
    rep = reg["report"]
    print("wrote %s task=%s %s.min_conf=%.2f coverage=%.3f abstention=%.3f "
          "train_n=%d (test split untouched, n=%d)"
          % (out, task, gate, rep["min_conf"], rep["coverage"],
             rep["abstention"], len(pool), len(test)))
    return 0


def report_error_count(store) -> int:
    """Print the store coding-bug count; nonzero fails loudly.

    Returns 0 when Store.error_count is 0, else prints the loud
    NONZERO line and returns 1 so the CLI exit code surfaces the
    coding bug instead of burying it.
    """
    n = store.error_count
    if n:
        print("CODING-BUG COUNT NONZERO (Store.error_count): %d; a coding "
              "bug fired on this store" % n)
        return 1
    print("coding-bug count (Store.error_count): 0")
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
    return report_error_count(store)


def do_quarantine_review(args) -> int:
    """List the quarantine queue for a human to triage."""
    store = Store(str(args.db))
    rows = store.quarantined()
    if not rows:
        print("quarantine: empty (nothing awaiting review in %s)" % args.db)
        return 0
    print("quarantine: %d item(s) awaiting human review in %s"
          % (len(rows), args.db))
    for qid, text, reason in rows:
        excerpt = " ".join(text.split())
        if len(excerpt) > 120:
            excerpt = excerpt[:117] + "..."
        print("qid=%d reason=%s text=%r" % (qid, reason, excerpt))
    return 0


def do_quarantine_approve(args) -> int:
    """Human approve: release one quarantined row live, reason logged."""
    store = Store(str(args.db))
    try:
        fid = store.approve_quarantine(args.qid, args.reason, actor="human")
    except KeyError:
        print("approve refused: no quarantined row qid %d in %s"
              % (args.qid, args.db))
        return 2
    except ValueError as e:
        print("approve refused: %s" % e)
        return 2
    print("approve: qid %d released as fact %d by human (reason=%r)"
          % (args.qid, fid, args.reason))
    return report_error_count(store)


def do_quarantine_deny(args) -> int:
    """Human deny: drop one quarantined row, reason logged."""
    store = Store(str(args.db))
    try:
        store.deny_quarantine(args.qid, args.reason, actor="human")
    except KeyError:
        print("deny refused: no quarantined row qid %d in %s"
              % (args.qid, args.db))
        return 2
    except ValueError as e:
        print("deny refused: %s" % e)
        return 2
    print("deny: qid %d dropped by human (reason=%r)" % (args.qid, args.reason))
    return report_error_count(store)


def do_redteam() -> int:
    """Fire the poison gauntlet: five attacks, all must fail closed."""
    from eval.gauntlet import run_gauntlet
    results, ok = run_gauntlet()
    print("redteam: %d attacks, all must fail closed "
          "(quarantine or deny, never admit)" % len(results))
    for r in results:
        print("%-18s %s (%s)" % (r["attack"],
                                 "PASS" if r["passed"] else "FAIL",
                                 r.get("detail", "")))
    if ok:
        print("REDTEAM PASS: every attack failed closed")
        return 0
    print("REDTEAM FAIL: an attack admitted what it should not")
    return 1


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
    p_conf = sub.add_parser(
        "conformal",
        help="tune per-gate confidence cutoffs on train split only "
        "(abstention reported)")
    p_conf.add_argument("--task", default="general-qa")
    p_conf.add_argument("--out", default=None)
    p_conf.add_argument("--gate", default="admit",
                        choices=("admit", "importance"))
    p_conf.add_argument("--target", type=float,
                        default=calmod.CONFORMAL_TARGET_COVERAGE,
                        help="target train coverage over non-abstained "
                        "cases (default 0.9)")
    p_ov = sub.add_parser(
        "override",
        help="named-human fact override: restore | retire | tombstone")
    p_ov.add_argument("--db", default="uncluttered.db",
                      help="SQLite store path (default: ./uncluttered.db)")
    p_ov.add_argument("--fact-id", type=int, required=True,
                      help="id of the fact to act on")
    p_ov.add_argument(
        "--action", required=True, choices=("restore", "retire", "tombstone"),
        help="restore: clear the tombstone fields and conflict marks "
             "(both sides) and go live again fully clean; "
             "retire: soft-tombstone the fact toward --target-id; "
             "tombstone: explicit alias of retire, same soft tombstone "
             "with actor human")
    p_ov.add_argument("--target-id", type=int, default=None,
                      help="replacement fact id; required by retire and "
                           "tombstone")
    p_ov.add_argument("--reason", default="",
                      help="free-text reason recorded on the tombstone")
    p_rev = sub.add_parser(
        "review",
        help="list the quarantine queue for human triage")
    p_rev.add_argument("--db", default="uncluttered.db",
                       help="SQLite store path (default: ./uncluttered.db)")
    p_appr = sub.add_parser(
        "approve",
        help="human approve: release one quarantined row live "
        "(reason logged, actor human)")
    p_appr.add_argument("--db", default="uncluttered.db",
                        help="SQLite store path (default: ./uncluttered.db)")
    p_appr.add_argument("--qid", type=int, required=True,
                        help="quarantine row id to release")
    p_appr.add_argument("--reason", required=True,
                        help="human reason, logged to the reviews table")
    p_deny = sub.add_parser(
        "deny",
        help="human deny: drop one quarantined row "
        "(reason logged, actor human)")
    p_deny.add_argument("--db", default="uncluttered.db",
                        help="SQLite store path (default: ./uncluttered.db)")
    p_deny.add_argument("--qid", type=int, required=True,
                        help="quarantine row id to drop")
    p_deny.add_argument("--reason", required=True,
                        help="human reason, logged to the reviews table")
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
    if args.command == "conformal":
        return do_conformal(args.task, args.out, args.gate, args.target)
    if args.command == "override":
        return do_override(args)
    if args.command == "review":
        return do_quarantine_review(args)
    if args.command == "approve":
        return do_quarantine_approve(args)
    if args.command == "deny":
        return do_quarantine_deny(args)
    if args.command == "redteam":
        return do_redteam()
    print("unclutter %s: not built until its phase" % args.command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
