"""One-command frozen eval: frozen train/test split, per-suite pass table,
admit precision/recall/F1, latency, cost estimate.

Labels are rule-generated templates and paraphrase variants; every case
carries provenance=synthetic-rule and no case is presented as a human
label. The report prints the case-file hash and the provenance on every
run. The judge here is the offline rule stub, never Jev; the report
says so.

Exit codes: 1 on any case failing, 2 on split, provenance, or tuning
contamination (unreadable artifacts fail closed), 3 on Jev rate limit.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import time
from pathlib import Path

from uncluttered_memory import supersede as supmod
from uncluttered_memory.calibrate import effective, load_registry
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.jev_client import (JevJudgeClient, RateLimited,
                                            RuleRelationJudge,
                                            rate_limited_message)
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store

CASES_FILE = Path(__file__).resolve().parents[1] / "eval" / "frozen.jsonl"

SUITES = ("admit", "importance", "dedupe", "contradict", "supersede",
          "rerank")

PROVENANCE = "synthetic-rule"

PRICE_INR_PER_M = 4.0
TOKENS_PER_ITEM = 475

# Contamination scan: strings at or above this token-overlap (Jaccard)
# against any test-split text are flagged. Short strings compare on the
# normalized form only.
CONTAMINATION_SIM = 0.8
CONTAMINATION_MIN_TOKENS = 3


class ArtifactError(Exception):
    """Unreadable or malformed tuning artifact: fail closed, never skip."""


def text_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_for_compare(t: str) -> str:
    """casefold, strip punctuation, collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", t.casefold()).split())


def token_set(t: str) -> frozenset:
    return frozenset(normalize_for_compare(t).split())


def token_overlap(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def load_cases(path) -> list:
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def case_strings(case: dict) -> list:
    """Every text-bearing string in a case, for contamination scans."""
    out: list = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k in ("id", "suite", "kind", "provenance", "expect",
                         "label", "gate"):
                    continue
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(case)
    return out


def case_key(c: dict) -> str:
    return c.get("suite", "") + "|" + str(c.get("kind", c.get("expect", "")))


def case_hash(c: dict) -> str:
    payload = {k: v for k, v in sorted(c.items()) if k not in ("id", "split")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_cases(cases: list):
    """Return an error string, or None when every case is well formed."""
    if not cases:
        return "no cases"
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            return "case %d is not a JSON object" % (i + 1)
        if c.get("suite") not in SUITES:
            return "case %d has unknown suite %r (known: %s)" % (
                i + 1, c.get("suite"), ", ".join(SUITES))
        if not c.get("kind"):
            return "case %d missing kind" % (i + 1)
        if c.get("provenance") != PROVENANCE:
            return ("case %d provenance=%r; the frozen set carries only "
                    "%s labels, never implied human labels"
                    % (i + 1, c.get("provenance"), PROVENANCE))
    return None


def split_cases(cases: list) -> tuple:
    """Deterministic 50/50 split, stratified by suite/kind, hash ordered."""
    groups: dict = {}
    for c in cases:
        groups.setdefault(case_key(c), []).append(c)
    train, test = [], []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=case_hash)
        cut = len(ordered) // 2
        train.extend(ordered[:cut])
        test.extend(ordered[cut:])
    return train, test


def prf(tp: int, fp: int, fn: int) -> tuple:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f)


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
    """Flag tuning artifacts that touch the test split.

    Exact strings and hashes, normalized form (casefold, punctuation
    stripped, whitespace collapsed), and token overlap at or above
    CONTAMINATION_SIM all flag. An unreadable or malformed artifact is
    a hard ArtifactError listing the file: the scan fails closed and
    never silently skips a target.
    """
    test_raw = set()
    test_norm = set()
    test_tokens = []
    test_hashes = set()
    for c in test_cases:
        for s in case_strings(c):
            test_raw.add(s)
            n = normalize_for_compare(s)
            if n:
                test_norm.add(n)
            test_tokens.append(token_set(s))
            test_hashes.add(text_hash(s))
    bad = []
    for p in paths:
        try:
            with open(p) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise ArtifactError(
                "unreadable tuning artifact %s (%s)" % (p, e))
        strs = set(artifact_strings(data))
        hit = bool(strs & test_raw)
        if not hit and {text_hash(s) for s in strs} & test_hashes:
            hit = True
        if not hit:
            for s in strs:
                n = normalize_for_compare(s)
                if n and n in test_norm:
                    hit = True
                    break
                toks = token_set(s)
                if len(toks) >= CONTAMINATION_MIN_TOKENS and any(
                        token_overlap(toks, tt) >= CONTAMINATION_SIM
                        for tt in test_tokens):
                    hit = True
                    break
        if hit:
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


def case_label(c: dict) -> str:
    if "text" in c:
        return c["text"]
    if "old" in c:
        return c["old"] + " -> " + c["new"]
    return c.get("id", "case")


def evaluate_suite(suite: str, cases: list, gate: Gate,
                   durable_min: float = 0.58) -> tuple:
    """Run one suite. Returns (rows, latencies_ms)."""
    rows, lat = [], []
    for c in cases:
        t0 = time.perf_counter()
        if suite == "admit":
            got = gate.decide(c["text"], importance_min=3,
                              durable_min=durable_min).action
            ok = got == c["expect"]
        elif suite == "importance":
            got = gate.judge.vote(c["text"], [], []).importance
            ok = got == c["expect"]
        elif suite == "dedupe":
            s = Store()
            a = s.put(c["text"], "eval")
            b = s.put(c["candidate"], "eval")
            got = "DUP" if a == b else "DISTINCT"
            ok = got == c["expect"]
        elif suite == "contradict":
            s = Store()
            old_id = s.put(c["old"], "eval")
            new_id = s.put(c["new"], "eval")
            dec = supmod.decide(c["old"], c["new"],
                                RuleRelationJudge(), RuleRelationJudge())
            applied = supmod.apply(s, old_id, new_id, dec)
            got = dec.action
            if c["expect"] == "CONFLICT":
                ok = (dec.action == "CONFLICT" and applied
                      and dec.relation == "conflict_unresolved"
                      and s.get(old_id)[4] is None
                      and s.get(new_id)[4] is None
                      and s.get(old_id)[7] == new_id
                      and s.get(new_id)[7] == old_id
                      and s.tombstoned() == []
                      and len(s.conflicts()) == 1)
            else:  # KEEP: unrelated or coexist, both live, nothing marked
                ok = (dec.action == "KEEP" and not applied
                      and s.get(old_id)[4] is None
                      and s.get(new_id)[4] is None
                      and s.get(old_id)[7] is None
                      and s.tombstoned() == []
                      and s.conflicts() == [])
        elif suite == "supersede":
            s = Store()
            old_id = s.put(c["old"], "eval")
            new_id = s.put(c["new"], "eval")
            dec = supmod.decide(c["old"], c["new"],
                                RuleRelationJudge(), RuleRelationJudge())
            applied = supmod.apply(s, old_id, new_id, dec)
            got = dec.action
            if c["expect"] == "TOMBSTONE":
                ok = (dec.action == "TOMBSTONE" and applied
                      and s.get(old_id)[4] == new_id
                      and any(t == c["new"] for _, t, _ in s.live()))
            else:  # KEEP
                ok = (dec.action == "KEEP" and not applied
                      and s.get(old_id)[4] is None
                      and s.get(new_id)[4] is None)
        elif suite == "rerank":
            cands = [(t, float(s)) for t, s in c["candidates"]]
            got = Recall().select(cands, gate=float(c.get("gate", 0.58)))
            ok = got == c["expect"]
        else:
            raise ValueError("unknown suite %r" % suite)
        lat.append((time.perf_counter() - t0) * 1000.0)
        rows.append((case_label(c), got, c["expect"], ok))
    return rows, lat


def cross_split_overlap(train: list, test: list) -> set:
    """Normalized texts that appear in both splits.

    Only strings of three or more tokens count: short labels (filler
    words, card ids) are legitimately reused and carry no leak risk.
    """
    tr = set()
    te = set()
    for c in train:
        tr |= {normalize_for_compare(s) for s in case_strings(c)}
    for c in test:
        te |= {normalize_for_compare(s) for s in case_strings(c)}
    tr = {s for s in tr if len(s.split()) >= 3}
    te = {s for s in te if len(s.split()) >= 3}
    return tr & te


def run_eval(cases_path=None, task: str = "general-qa",
             registry_path=None, root=None, judge=None) -> int:
    cases_path = cases_path or CASES_FILE
    root = root or Path(cases_path).resolve().parents[1]
    cases = load_cases(cases_path)
    err = validate_cases(cases)
    if err:
        print("CASES ERROR: %s" % err)
        return 2
    train, test = split_cases(cases)

    tr_hashes = {case_hash(c) for c in train}
    te_hashes = {case_hash(c) for c in test}
    if not tr_hashes.isdisjoint(te_hashes):
        print("CONTAMINATION: train/test case overlap")
        return 2
    if cross_split_overlap(train, test):
        print("CONTAMINATION: train/test normalized text overlap")
        return 2
    try:
        bad = find_bad_artifacts(test, default_artifact_paths(root,
                                                              registry_path))
    except ArtifactError as e:
        print("CONTAMINATION: %s; scan fails closed, nothing was scored" % e)
        return 2
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
        results = {}
        lat = []
        for suite in SUITES:
            tr_cases = [c for c in train if c["suite"] == suite]
            te_cases = [c for c in test if c["suite"] == suite]
            tr_rows, tr_lat = evaluate_suite(suite, tr_cases, gate, durable_min)
            te_rows, te_lat = evaluate_suite(suite, te_cases, gate, durable_min)
            results[suite] = (tr_rows, te_rows)
            lat += tr_lat + te_lat
    except RateLimited as e:
        print("JEV RATE LIMITED: " + rate_limited_message(e))
        print("eval halted: nothing was voted or charged")
        return 3

    print("unclutter eval: n=%d train=%d test=%d (%s)" %
          (len(cases), len(train), len(test), reg_note))
    print("cases sha256: %s" % file_sha256(cases_path))
    print("labels: provenance=%s (rule-generated; no human labels)"
          % PROVENANCE)
    print("judge=rule-stub (offline heuristic, not Jev)"
          if not isinstance(gate.judge, JevJudgeClient) else
          "judge=jev-1.13-free (live)")
    total_fails = 0
    for suite in SUITES:
        for name, rows in (("train", results[suite][0]),
                           ("test", results[suite][1])):
            ok_n = sum(1 for r in rows if r[3])
            fails = len(rows) - ok_n
            total_fails += fails
            if suite == "admit" and rows:
                p, r, f = admit_prf(rows)
                print("%-10s %-5s p=%.3f r=%.3f f=%.3f  n=%d ok=%d fail=%d"
                      % (suite, name, p, r, f, len(rows), ok_n, fails))
            else:
                print("%-10s %-5s n=%d ok=%d fail=%d"
                      % (suite, name, len(rows), ok_n, fails))

    for suite in SUITES:
        for name, rows in (("train", results[suite][0]),
                           ("test", results[suite][1])):
            for label, got, exp, ok in rows:
                if not ok:
                    print("[FAIL] %s/%s %r: got %r, expect %r"
                          % (suite, name, label, got, exp))
    print("latency judge ms: p50=%.3f p95=%.3f (n=%d, offline stub)"
          % (pct(lat, 0.5), pct(lat, 0.95), len(lat)))
    cost = 1000 * TOKENS_PER_ITEM * PRICE_INR_PER_M / 1e6
    print("cost per 1k writes: ESTIMATE INR %.2f"
          " (formula 1000*%d tokens * INR %.1f/1M, NOT VERIFIED)" %
          (cost, TOKENS_PER_ITEM, PRICE_INR_PER_M))
    print("contamination: ok (train/test disjoint by case hash and"
          " normalized text, artifacts fail closed)")
    print("%s: %d failures" % ("PASS" if not total_fails else "FAIL",
                               total_fails))
    return 1 if total_fails else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="unclutter-eval")
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--registry", default=None)
    parser.add_argument("--task", default="general-qa")
    args = parser.parse_args(argv)
    return run_eval(args.cases, task=args.task, registry_path=args.registry)


if __name__ == "__main__":
    raise SystemExit(main())
