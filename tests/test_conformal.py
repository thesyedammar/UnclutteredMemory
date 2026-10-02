"""Conformal calibration: per-gate confidence cutoffs, train only.

Thresholds are tuned on the train split only (test split is a hard
refusal), the registry embeds no case text (the contamination scan
passes on it), and the abstention rate is reported on every run.
"""
import json

import pytest

from uncluttered_memory import calibrate as calmod
from uncluttered_memory import cli as climod
from uncluttered_memory.calibrate import (CalibrationError,
                                           calibrate_confidence,
                                           tune_conformal_threshold)
from eval.run import find_bad_artifacts


def test_tune_picks_lowest_cutoff_meeting_target():
    scored = [(0.9, True), (0.8, True), (0.2, False), (0.1, False)]
    best = tune_conformal_threshold(scored, candidates=(0.0, 0.5, 0.9),
                                    target_coverage=0.9)
    assert best["min_conf"] == 0.5
    assert best["coverage"] == 1.0
    assert best["abstention"] == pytest.approx(0.5)
    assert best["kept"] == 2 and best["abstained"] == 2


def test_tune_fails_closed_to_highest_cutoff_when_target_missed():
    scored = [(0.9, True), (0.8, False), (0.7, False)]
    best = tune_conformal_threshold(scored, candidates=(0.0, 0.5, 0.9),
                                    target_coverage=0.99)
    assert best["min_conf"] == 0.9
    assert best["coverage"] < 0.99 or best["kept"] <= 1


def test_tune_empty_scored_is_a_hard_error():
    with pytest.raises(CalibrationError):
        tune_conformal_threshold([], candidates=(0.0, 0.5))


def test_calibrate_confidence_refuses_test_split(tmp_path):
    out = str(tmp_path / "reg.json")
    cases = [{"text": "x", "expect": "STORE", "split": "test"}]
    with pytest.raises(CalibrationError):
        calibrate_confidence(cases, "t", out, lambda c: 0.9,
                             lambda c: True, gate="admit")


def test_calibrate_confidence_writes_per_gate_cutoff(tmp_path):
    out = str(tmp_path / "reg.json")
    cases = [{"text": "keep %d percent" % i, "expect": "STORE"}
             for i in range(6)]
    cases += [{"text": "ok", "expect": "DROP"} for _ in range(2)]
    reg = calibrate_confidence(
        cases, "alpha", out,
        lambda c: 0.85 if c["expect"] == "STORE" else 0.2,
        lambda c: True, gate="admit")
    assert reg["thresholds"]["admit.min_conf"] == reg["report"]["min_conf"]
    assert 0.0 <= reg["report"]["abstention"] <= 1.0
    assert reg["report"]["n"] == 8
    loaded = json.loads(open(out, encoding="utf-8").read())
    assert loaded["thresholds"]["admit.min_conf"] == reg["report"]["min_conf"]
    assert loaded["conformal"]["admit"]["abstention"] == reg["report"]["abstention"]


def test_conformal_registry_passes_contamination_scan(tmp_path):
    out = tmp_path / "reg.json"
    cases = [{"text": "my stop loss is 8 percent", "expect": "STORE"},
             {"text": "ok", "expect": "DROP"}]
    calibrate_confidence(cases, "alpha", str(out), lambda c: 0.9,
                         lambda c: True, gate="admit")
    test_cases = [{"id": "t1", "suite": "admit", "kind": "k",
                   "provenance": "synthetic-rule", "expect": "STORE",
                   "text": "my stop loss is 8 percent"}]
    assert find_bad_artifacts(test_cases, [str(out)]) == []


def test_cli_conformal_train_only_reports_abstention(tmp_path, capsys):
    out = str(tmp_path / "conf.json")
    rc = climod.main(["conformal", "--task", "general-qa",
                      "--out", out, "--gate", "admit"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "admit.min_conf" in printed
    assert "abstention=" in printed
    assert "test split untouched" in printed
    reg = json.loads(open(out, encoding="utf-8").read())
    assert "admit.min_conf" in reg["thresholds"]


def test_cli_conformal_importance_gate(tmp_path, capsys):
    out = str(tmp_path / "conf.json")
    rc = climod.main(["conformal", "--task", "general-qa",
                      "--out", out, "--gate", "importance"])
    assert rc == 0
    assert "importance.min_conf" in capsys.readouterr().out
    reg = json.loads(open(out, encoding="utf-8").read())
    assert "importance.min_conf" in reg["thresholds"]
