"""One-command frozen eval: frozen train/test split, per-suite pass table,
admit precision/recall/F1, latency, cost estimate.

Two case sets, two jobs:

- eval/frozen.jsonl is the BULK set: rule-generated templates and
  paraphrase variants whose labels are pinned to the documented rule
  stubs. It is a self-consistency check of the frozen harness, never a
  benchmark claim, and its numbers are reported as such.
- eval/golden.jsonl is the GOLDEN set: hand-authored cases written as
  data (text plus expected label), authored against the documented gate
  contract, sharing no code path with the stubs. The headline numbers
  come from golden; the runner refuses to run without it.

The judge here is the offline rule stub, never Jev; the report says so.
Every offline decide() call runs through the heterogeneous strict +
lenient relation pair, so an agreed destructive act means two distinct
heuristics agreed.

The report stream is forced to UTF-8 with an explicit error handler
(uncluttered_memory.console) and the success line is pinned byte for
byte by tests.

Exit codes: 1 on any golden or bulk case failing (headline is golden),
2 on split, provenance, golden, or tuning contamination (unreadable
artifacts fail closed), 3 on Jev rate limit.
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
from uncluttered_memory import thresholds as th
from uncluttered_memory.calibrate import effective, load_registry
from uncluttered_memory.console import configure_console
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.jev_client import (JevJudgeClient, RateLimited,
                                            offline_relation_pair,
                                            rate_limited_message)
from uncluttered_memory.recall import Recall
from uncluttered_memory.store import Store

CASES_FILE = Path(__file__).resolve().parents[1] / "eval" / "frozen.jsonl"
GOLDEN_FILE = Path(__file__).resolve().parents[1] / "eval" / "golden.jsonl"

SUITES = ("admit", "importance", "dedupe", "contradict", "supersede",
          "rerank")

PROVENANCE = "synthetic-rule"
GOLDEN_PROVENANCE = "hand-authored"

#: The golden claim set may not shrink below this floor unnoticed.
GOLDEN_MIN_CASES = 120

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
    with open(path, encoding="utf-8") as f:
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


def validate_cases(cases: list, provenance: str = PROVENANCE):
    """Return an error string, or None when every case is well formed.

    The expected provenance is a parameter: the bulk set carries
    synthetic-rule labels only, the golden set carries hand-authored
    labels only, and neither is ever presented as the other.
    """
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
        if c.get("provenance") != provenance:
            return ("case %d provenance=%r; expected %r "
                    "(bulk cases carry %s, golden cases carry %s)"
                    % (i + 1, c.get("provenance"), provenance,
                       PROVENANCE, GOLDEN_PROVENANCE))
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


EXCERPT_MAX = 120


def _excerpt(s: str, limit: int = EXCERPT_MAX) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit - 3] + "..."


def artifact_flag(path, check: str, score, excerpt: str) -> dict:
    """One machine-readable contamination flag.

    check names the scan that fired (exact-text, content-hash,
    normalized-text, token-overlap, split-field); score is the match
    strength (1.0 for the equality checks, the best Jaccard score for
    token-overlap, None when the check is metadata rather than text);
    excerpt is the offending string (or field), truncated.
    """
    return {"path": str(path), "check": check, "score": score,
            "excerpt": _excerpt(excerpt)}


def format_artifact_flag(flag: dict) -> str:
    """One report line: path, check, score, excerpt. No bare flags."""
    score = "%.3f" % flag["score"] if flag["score"] is not None else "n/a"
    return ("%s check=%s score=%s excerpt=%r"
            % (flag["path"], flag["check"], score, flag["excerpt"]))


def find_bad_artifacts(test_cases: list, paths: list) -> list:
    """Flag tuning artifacts that touch an eval set. One flag per file.

    Returns machine-readable flags (dicts with path, check, score,
    excerpt). The first check that fires, in priority order, is the
    one reported: exact-text; content-hash (the artifact embeds the
    content hash of an eval text); normalized-text (casefold,
    punctuation stripped, whitespace collapsed); token-overlap at or
    above CONTAMINATION_SIM (with the best Jaccard score found); then
    split-field (metadata says split=test or tuned_on=test). An
    unreadable or malformed artifact is a hard ArtifactError listing
    the file: the scan fails closed and never silently skips a target.
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
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise ArtifactError(
                "unreadable tuning artifact %s (%s)" % (p, e))
        strs = sorted(set(artifact_strings(data)))
        flag = None
        for s in strs:
            if s in test_raw:
                flag = artifact_flag(p, "exact-text", 1.0, s)
                break
        if flag is None:
            for s in strs:
                if s in test_hashes:
                    flag = artifact_flag(p, "content-hash", 1.0, s)
                    break
        if flag is None:
            for s in strs:
                n = normalize_for_compare(s)
                if n and n in test_norm:
                    flag = artifact_flag(p, "normalized-text", 1.0, s)
                    break
        if flag is None:
            best = (0.0, "")
            for s in strs:
                toks = token_set(s)
                if len(toks) < CONTAMINATION_MIN_TOKENS:
                    continue
                for tt in test_tokens:
                    ov = token_overlap(toks, tt)
                    if ov > best[0]:
                        best = (ov, s)
            if best[0] >= CONTAMINATION_SIM:
                flag = artifact_flag(p, "token-overlap", best[0], best[1])
        if flag is None and isinstance(data, dict) and (
                data.get("split") == "test" or data.get("tuned_on") == "test"):
            field = ("split=test" if data.get("split") == "test"
                     else "tuned_on=test")
            flag = artifact_flag(p, "split-field", None, field)
        if flag is not None:
            bad.append(flag)
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


def relation_judge_pair() -> tuple:
    """The offline decide() pair: two distinct heuristics, never a copy.

    Strict + lenient, heterogeneous by construction (see
    jev_client.offline_relation_pair). Every offline relation call in
    the eval routes through this mismatched pair, so a destructive act
    only proceeds when two genuinely different readings agree.
    """
    return offline_relation_pair()


def evaluate_suite(suite: str, cases: list, gate: Gate,
                   durable_min: float = th.DURABLE_MIN) -> tuple:
    """Run one suite. Returns (rows, latencies_ms)."""
    rows, lat = [], []
    for c in cases:
        t0 = time.perf_counter()
        if suite == "admit":
            got = gate.decide(c["text"], importance_min=th.IMPORTANCE_MIN,
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
            dec = supmod.decide(c["old"], c["new"], *relation_judge_pair())
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
            dec = supmod.decide(c["old"], c["new"], *relation_judge_pair())
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
            got = Recall().select(cands, gate=float(c.get("gate",
                                                           th.RECALL_GATE)))
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


def load_golden(path) -> tuple:
    """Load and validate the golden claim set. Returns (cases, error)."""
    p = Path(path)
    if not p.exists():
        return [], ("no golden set at %s; the headline claim rests on "
                    "golden, so this is a hard error" % p)
    try:
        cases = load_cases(p)
    except (OSError, ValueError) as e:
        return [], "unreadable golden set %s (%s)" % (p, e)
    err = validate_cases(cases, GOLDEN_PROVENANCE)
    if err:
        return [], "golden set invalid: %s" % err
    if len(cases) < GOLDEN_MIN_CASES:
        return [], ("golden set has %d cases; the documented floor is %d"
                    % (len(cases), GOLDEN_MIN_CASES))
    missing = [s for s in SUITES if not any(c["suite"] == s for c in cases)]
    if missing:
        return [], ("golden set misses suite(s): %s" % ", ".join(missing))
    return cases, None


def run_eval(cases_path=None, task: str = "general-qa",
             registry_path=None, root=None, judge=None,
             golden_path: "str | Path | None" = GOLDEN_FILE) -> int:
    configure_console()
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
        for f in bad:
            print("  " + format_artifact_flag(f))
        return 2

    golden = []
    if golden_path is not None:
        golden, gerr = load_golden(golden_path)
        if gerr:
            print("GOLDEN ERROR: %s" % gerr)
            return 2
        if cross_split_overlap(cases, golden):
            print("GOLDEN ERROR: golden text overlaps the bulk set; the "
                  "claim set must be independent of the self-consistency "
                  "set")
            return 2
        try:
            badg = find_bad_artifacts(
                golden, default_artifact_paths(root, registry_path))
        except ArtifactError as e:
            print("CONTAMINATION: %s; scan fails closed, nothing was scored"
                  % e)
            return 2
        if badg:
            print("CONTAMINATION: tuning artifacts touch the golden set:")
            for f in badg:
                print("  " + format_artifact_flag(f))
            return 2

    durable_min = th.DURABLE_MIN
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
        golden_results = {}
        for suite in SUITES:
            g_cases = [c for c in golden if c["suite"] == suite]
            g_rows, g_lat = evaluate_suite(suite, g_cases, gate, durable_min)
            golden_results[suite] = g_rows
            lat += g_lat
    except RateLimited as e:
        print("JEV RATE LIMITED: " + rate_limited_message(e))
        print("eval halted: nothing was voted or charged")
        return 3

    print("unclutter eval: bulk n=%d train=%d test=%d (%s)" %
          (len(cases), len(train), len(test), reg_note))
    if golden:
        print("golden: n=%d hand-authored cases (headline claim; evaluated "
              "whole, never split, never tuned on)" % len(golden))
    else:
        print("golden: skipped (no golden path); bulk only, no headline "
              "claim")
    print("cases sha256: %s" % file_sha256(cases_path))
    if golden:
        print("golden sha256: %s" % file_sha256(golden_path))
    label_line = ("labels: bulk provenance=%s (rule-generated "
                  "self-consistency; no human labels)" % PROVENANCE)
    if golden:
        label_line += ("; golden provenance=%s (the claim set)"
                       % GOLDEN_PROVENANCE)
    print(label_line)
    print("judge=rule-stub (offline heuristic, not Jev)"
          if not isinstance(gate.judge, JevJudgeClient) else
          "judge=jev-1.13-free (live)")

    bulk_fails = 0
    bulk_total = 0
    bulk_ok = 0
    if golden:
        print("GOLDEN (hand-authored claim set, evaluated whole)")
        for suite in SUITES:
            rows = golden_results[suite]
            ok_n = sum(1 for r in rows if r[3])
            fails = len(rows) - ok_n
            if suite == "admit" and rows:
                p, r, f = admit_prf(rows)
                print("%-10s %-6s p=%.3f r=%.3f f=%.3f  n=%d ok=%d fail=%d"
                      % (suite, "golden", p, r, f, len(rows), ok_n, fails))
            else:
                print("%-10s %-6s n=%d ok=%d fail=%d"
                      % (suite, "golden", len(rows), ok_n, fails))
    print("BULK (synthetic-rule; self-consistency only, NOT a benchmark "
          "claim)")
    for suite in SUITES:
        for name, rows in (("train", results[suite][0]),
                           ("test", results[suite][1])):
            ok_n = sum(1 for r in rows if r[3])
            fails = len(rows) - ok_n
            bulk_fails += fails
            bulk_total += len(rows)
            bulk_ok += ok_n
            if suite == "admit" and rows:
                p, r, f = admit_prf(rows)
                print("%-10s %-6s p=%.3f r=%.3f f=%.3f  n=%d ok=%d fail=%d"
                      % (suite, name, p, r, f, len(rows), ok_n, fails))
            else:
                print("%-10s %-6s n=%d ok=%d fail=%d"
                      % (suite, name, len(rows), ok_n, fails))

    golden_fails = 0
    golden_total = 0
    golden_ok = 0
    if golden:
        for suite in SUITES:
            rows = golden_results[suite]
            for label, got, exp, ok in rows:
                golden_total += 1
                if ok:
                    golden_ok += 1
                else:
                    golden_fails += 1
                    print("[FAIL] GOLDEN %s %r: got %r, expect %r"
                          % (suite, label, got, exp))
    for suite in SUITES:
        for name, rows in (("train", results[suite][0]),
                           ("test", results[suite][1])):
            for label, got, exp, ok in rows:
                if not ok:
                    print("[FAIL] BULK %s/%s %r: got %r, expect %r"
                          % (suite, name, label, got, exp))

    if golden:
        print("HEADLINE (golden, hand-authored): %d/%d ok, %d failures"
              % (golden_ok, golden_total, golden_fails))
    print("bulk self-consistency (synthetic-rule): %d/%d ok, %d failures"
          % (bulk_ok, bulk_total, bulk_fails))
    print("latency judge ms: p50=%.3f p95=%.3f (n=%d, offline stub)"
          % (pct(lat, 0.5), pct(lat, 0.95), len(lat)))
    cost = 1000 * TOKENS_PER_ITEM * PRICE_INR_PER_M / 1e6
    print("cost per 1k writes: ESTIMATE INR %.2f"
          " (formula 1000*%d tokens * INR %.1f/1M, NOT VERIFIED)" %
          (cost, TOKENS_PER_ITEM, PRICE_INR_PER_M))
    print("contamination: ok (train/test disjoint by case hash and"
          " normalized text, golden disjoint from bulk, artifacts fail"
          " closed)")
    if golden:
        status = "PASS" if not (golden_fails or bulk_fails) else "FAIL"
        print("%s: golden %d failures, bulk %d failures"
              % (status, golden_fails, bulk_fails))
        return 1 if (golden_fails or bulk_fails) else 0
    status = "PASS" if not bulk_fails else "FAIL"
    print("%s: bulk %d failures (no golden set loaded)" % (status, bulk_fails))
    return 1 if bulk_fails else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="unclutter-eval")
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--golden", default=str(GOLDEN_FILE),
                        help="golden case file; 'none' skips it")
    parser.add_argument("--registry", default=None)
    parser.add_argument("--task", default="general-qa")
    args = parser.parse_args(argv)
    golden = None if args.golden.lower() == "none" else args.golden
    return run_eval(args.cases, task=args.task, registry_path=args.registry,
                    golden_path=golden)


if __name__ == "__main__":
    raise SystemExit(main())
