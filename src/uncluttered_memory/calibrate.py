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
