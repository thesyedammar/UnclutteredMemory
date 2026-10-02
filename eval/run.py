"""One-command frozen eval: 50/50 split, per-gate PRF, latency, cost estimate.

Judge is the offline rule stub here, never Jev; the report says so.
Exits 1 on label mismatch, 2 on split or tuning contamination.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import time
from pathlib import Path

from uncluttered_memory.calibrate import effective, load_registry
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.jev_client import (JevJudgeClient, RateLimited,
                                            rate_limited_message)

CASES_FILE = Path(__file__).resolve().parents[1] / "eval" / "frozen.jsonl"

PRICE_INR_PER_M = 4.0
TOKENS_PER_ITEM = 475


def text_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def load_cases(path) -> list:
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def case_key(c: dict) -> str:
    return c.get("suite", "") + "|" + c.get("expect", c.get("label", ""))


def split_cases(cases: list) -> tuple:
    """Deterministic 50/50 split, stratified by suite/label, hash ordered."""
    groups: dict = {}
    for c in cases:
        groups.setdefault(case_key(c), []).append(c)
    train, test = [], []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=lambda c: text_hash(c["text"]))
        cut = len(ordered) // 2
        train.extend(ordered[:cut])
        test.extend(ordered[cut:])
    return train, test


def prf(tp: int, fp: int, fn: int) -> tuple:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f)


def evaluate(cases: list, gate: Gate, durable_min: float = 0.58) -> tuple:
    rows, fails, lat = [], 0, []
    for c in cases:
        t0 = time.perf_counter()
        got = gate.decide(c["text"], importance_min=3,
                          durable_min=durable_min).action
        lat.append((time.perf_counter() - t0) * 1000.0)
        ok = got == c.get("expect", c.get("label"))
        fails += 0 if ok else 1
        rows.append((c["text"], got, c.get("expect", c.get("label")), ok))
    return rows, fails, lat


def admit_prf(rows: list) -> tuple:
    tp = sum(1 for _, got, exp, _ in rows if got == "STORE" and exp == "STORE")
    fp = sum(1 for _, got, exp, _ in rows if got == "STORE" and exp != "STORE")
    fn = sum(1 for _, got, exp, _ in rows if got != "STORE" and exp == "STORE")
    return prf(tp, fp, fn)


def pct(vals: list, q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def artifact_strings(obj) -> list:
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(artifact_strings(v))
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out.extend(artifact_strings(v))
        return out
    return [obj] if isinstance(obj, str) else []


def find_bad_artifacts(test_cases: list, paths: list) -> list:
    texts = {c["text"] for c in test_cases}
    hashes = {text_hash(c["text"]) for c in test_cases}
    bad = []
    for p in paths:
        try:
            with open(p) as f:
                data = json.load(f)
        except Exception:
            continue
        strs = set(artifact_strings(data))
        if strs & texts or strs & hashes:
            bad.append(p)
            continue
        if isinstance(data, dict) and (
                data.get("split") == "test" or data.get("tuned_on") == "test"):
            bad.append(p)
    return bad


def default_artifact_paths(root: Path, extra=None) -> list:
    paths = glob.glob(str(root / "thresholds" / "*.json"))
    paths += glob.glob(str(root / "eval" / "thresholds*.json"))
    if extra:
        paths.append(extra)
    return sorted(set(paths))


def run_eval(cases_path=None, task: str = "general-qa",
             registry_path=None, root=None, judge=None) -> int:
    cases_path = cases_path or CASES_FILE
    root = root or Path(cases_path).resolve().parents[1]
    cases = load_cases(cases_path)
    train, test = split_cases(cases)

    tr_hashes = {text_hash(c["text"]) for c in train}
    te_hashes = {text_hash(c["text"]) for c in test}
    if not tr_hashes.isdisjoint(te_hashes):
        print("CONTAMINATION: train/test text overlap")
        return 2
    bad = find_bad_artifacts(test, default_artifact_paths(root, registry_path))
    if bad:
        print("CONTAMINATION: tuning artifacts touch test split:")
        for p in bad:
            print("  " + p)
        return 2

    durable_min = 0.58
    reg_note = "uncalibrated defaults"
    if registry_path:
        try:
            reg = load_registry(registry_path, task)
        except Exception as e:
            print("registry error: %s" % e)
            return 2
        val = effective(reg, "admit.durable", task)
        if val != "UNCALIBRATED":
            durable_min = float(val)
        reg_note = "registry %s task=%s" % (registry_path, task)

    gate = Gate(judge or RuleJudge())
    try:
        train_rows, train_fails, train_lat = evaluate(train, gate, durable_min)
        test_rows, test_fails, test_lat = evaluate(test, gate, durable_min)
    except RateLimited as e:
        print("JEV RATE LIMITED: " + rate_limited_message(e))
        print("eval halted: nothing was voted or charged")
        return 3
    lat = train_lat + test_lat

    print("unclutter eval: n=%d train=%d test=%d (%s)" %
          (len(cases), len(train), len(test), reg_note))
    print("judge=rule-stub (offline heuristic, not Jev)"
          if not isinstance(gate.judge, JevJudgeClient) else
          "judge=jev-1.13-free (live)")
    for name, rows in (("train", train_rows), ("test", test_rows)):
        p, r, f = admit_prf(rows)
        print("admit   %-5s  %.3f  %.3f  %.3f  %d" % (name, p, r, f, len(rows)))
    print("supersede test   no cases (n=0)")
    print("recall    test   no cases (n=0)")
    for text, got, exp, ok in test_rows:
        print("[%s] %r: got %s, expect %s" % ("ok" if ok else "FAIL", text, got, exp))
    cost = 1000 * TOKENS_PER_ITEM * PRICE_INR_PER_M / 1e6
    print("latency judge ms: p50=%.3f p95=%.3f (n=%d, offline stub)" %
          (pct(lat, 0.5), pct(lat, 0.95), len(lat)))
    print("cost per 1k writes: ESTIMATE INR %.2f"
          " (formula 1000*%d tokens * INR %.1f/1M, NOT VERIFIED)" %
          (cost, TOKENS_PER_ITEM, PRICE_INR_PER_M))
    print("contamination: ok (train/test disjoint, test untouched by tuning)")
    fails = train_fails + test_fails
    print("%s: %d failures" % ("PASS" if not fails else "FAIL", fails))
    return 1 if fails else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="unclutter-eval")
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--registry", default=None)
    parser.add_argument("--task", default="general-qa")
    args = parser.parse_args(argv)
    return run_eval(args.cases, task=args.task, registry_path=args.registry)


if __name__ == "__main__":
    raise SystemExit(main())
