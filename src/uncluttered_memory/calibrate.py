"""Per-task threshold registry: fingerprinted, train-only, UNCALIBRATED default.

A registry file belongs to exactly one task. Loading it for any other
task is a hard error. Fresh installs have no registry and stay
UNCALIBRATED until the train-only tuning command writes one.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

UNCALIBRATED = "UNCALIBRATED"


class CalibrationError(Exception):
    pass


class MissingCalibration(CalibrationError):
    pass


def fingerprint(task: str) -> str:
    return hashlib.sha256(task.encode()).hexdigest()


def train_hash(texts: list) -> str:
    hs = sorted(hashlib.sha256(t.encode()).hexdigest() for t in texts)
    return hashlib.sha256(",".join(hs).encode()).hexdigest()


def prf(tp: int, fp: int, fn: int) -> tuple:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f)


def tune_threshold(scored: list, candidates=None) -> dict:
    """scored: [(score, is_positive)]. Sweep cutoffs, keep best F1."""
    if candidates is None:
        candidates = (0.3, 0.4, 0.5, 0.58, 0.6, 0.7, 0.8)
    best = None
    for t in candidates:
        tp = sum(1 for s, y in scored if s >= t and y)
        fp = sum(1 for s, y in scored if s >= t and not y)
        fn = sum(1 for s, y in scored if s < t and y)
        p, r, f = prf(tp, fp, fn)
        row = {"threshold": t, "precision": p, "recall": r, "f1": f,
               "tp": tp, "fp": fp, "fn": fn}
        if best is None or (f, -t) > (best["f1"], -best["threshold"]):
            best = row
    assert best is not None
    return best


def calibrate_gate(train_cases: list, task: str, out_path: str, get_score) -> dict:
    """Tune one gate cutoff on train cases only. get_score(case) -> float.

    Positive label is expect/label == STORE. Any case tagged split=test
    is a hard error: tuning never touches the test split.
    """
    for c in train_cases:
        if c.get("split") == "test":
            raise CalibrationError("refusing to tune on test split")
    scored = [(get_score(c), c.get("expect", c.get("label")) == "STORE")
              for c in train_cases]
    best = tune_threshold(scored)
    reg = {"task": task, "fingerprint": fingerprint(task),
           "thresholds": {"admit.durable": best["threshold"]},
           "train_hash": train_hash([c.get("text", "") for c in train_cases]),
           "train_n": len(train_cases), "train_f1": best["f1"]}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(reg, f, indent=2)
    reg["report"] = best
    return reg


#: Conformal confidence candidates: min_conf cutoffs swept per gate.
#: Low confidence abstains to quarantine, so a higher cutoff means a
#: higher abstention rate and fewer wrong admits.
CONFORMAL_CANDIDATES = (0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9)

#: Default target coverage: the tuned cutoff is the lowest candidate
#: whose train correctness on non-abstained cases meets this rate.
#: Higher targets abstain more.
CONFORMAL_TARGET_COVERAGE = 0.9


def tune_conformal_threshold(scored: list,
                             candidates=None,
                             target_coverage: float = CONFORMAL_TARGET_COVERAGE
                             ) -> dict:
    """Pick the lowest min_conf cutoff meeting target train coverage.

    scored: [(confidence, is_correct)]. Cases below the cutoff
    abstain (quarantine); coverage is the correct rate over the
    non-abstained cases. The lowest cutoff meeting the target wins
    (least abstention for the coverage); when none meets it, the
    highest cutoff wins (most abstention, fail closed). Empty scored
    is a CalibrationError: no threshold is invented from no data.
    """
    if not scored:
        raise CalibrationError("no train cases to tune confidence on")
    if candidates is None:
        candidates = CONFORMAL_CANDIDATES
    rows = []
    for cutoff in sorted(candidates):
        kept = [(c, y) for c, y in scored if c >= cutoff]
        abst = len(scored) - len(kept)
        abstention = abst / len(scored)
        if kept:
            coverage = sum(1 for _, y in kept if y) / len(kept)
        else:
            coverage = 1.0
        rows.append({"min_conf": cutoff, "coverage": coverage,
                     "abstention": abstention,
                     "kept": len(kept), "abstained": abst,
                     "n": len(scored)})
    meeting = [r for r in rows if r["coverage"] >= target_coverage]
    if meeting:
        return min(meeting, key=lambda r: r["min_conf"])
    return max(rows, key=lambda r: r["min_conf"])


def calibrate_confidence(train_cases: list, task: str, out_path: str,
                         get_conf, is_correct,
                         target_coverage: float = CONFORMAL_TARGET_COVERAGE,
                         candidates=None,
                         gate: str = "admit") -> dict:
    """Tune one per-gate min_conf cutoff on train cases only.

    get_conf(case) -> judge confidence float; is_correct(case) -> bool
    scores the non-abstained verdict against the golden expect. Any
    case tagged split=test is a hard error. The registry records the
    tuned cutoff under <gate>.min_conf plus the train abstention
    rate; it embeds no case text, so the contamination scan passes.
    """
    for c in train_cases:
        if c.get("split") == "test":
            raise CalibrationError("refusing to tune on test split")
    scored = [(float(get_conf(c)), bool(is_correct(c)))
              for c in train_cases]
    best = tune_conformal_threshold(scored, candidates, target_coverage)
    try:
        with open(out_path, encoding="utf-8") as f:
            reg = json.load(f)
        if reg.get("task") != task or reg.get("fingerprint") != fingerprint(task):
            raise CalibrationError(
                "registry for task %r refuses task %r"
                % (reg.get("task"), task))
    except FileNotFoundError:
        reg = {"task": task, "fingerprint": fingerprint(task),
               "thresholds": {},
               "train_hash": train_hash(
                   [str(c.get("text", c.get("id", "")))
                    for c in train_cases]),
               "train_n": 0, "train_f1": 0.0}
    reg["thresholds"]["%s.min_conf" % gate] = best["min_conf"]
    reg["train_n"] = len(train_cases)
    reg["conformal"] = {gate: best, "target_coverage": target_coverage}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(reg, f, indent=2)
    reg["report"] = best
    return reg


def load_registry(path: str, task: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise MissingCalibration("no registry at %s for task %s" % (path, task))
    with open(p) as f:
        data = json.load(f)
    if data.get("task") != task or data.get("fingerprint") != fingerprint(task):
        raise CalibrationError(
            "registry for task %r refuses task %r" % (data.get("task"), task))
    return data


def effective(registry, key: str, task: str):
    """Look up one threshold. Returns UNCALIBRATED when nothing is tuned."""
    if registry is None:
        return UNCALIBRATED
    if registry.get("task") != task:
        raise CalibrationError("registry task mismatch for key %s" % key)
    return registry.get("thresholds", {}).get(key, UNCALIBRATED)
