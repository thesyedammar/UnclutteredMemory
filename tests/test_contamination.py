"""Contamination checks: fail closed on unreadable artifacts, and catch
paraphrased leaks via normalized comparison and token overlap.

An artifact that cannot be parsed is a hard ArtifactError that lists
the file; the scan never silently skips a target.
"""
import json
from pathlib import Path

import pytest

from eval import run as evalmod
from eval.run import (ArtifactError, CONTAMINATION_SIM, find_bad_artifacts,
                      run_eval)

TEST_CASES = [
    {"id": "t1", "suite": "admit", "kind": "durable-percent",
     "provenance": "synthetic-rule", "expect": "STORE",
     "text": "my stop loss is 8 percent"},
    {"id": "t2", "suite": "admit", "kind": "durable-deadline",
     "provenance": "synthetic-rule", "expect": "STORE",
     "text": "the report deadline is friday"},
]


def write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return p


def test_exact_string_touch_flagged(tmp_path):
    p = write(tmp_path, "a.json", {"note": "my stop loss is 8 percent"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == [str(p)]


def test_normalized_paraphrase_flagged(tmp_path):
    # casefold + punctuation strip + whitespace collapse make this equal
    # to the test text only after normalization.
    p = write(tmp_path, "a.json",
              {"note": "  My  STOP-LOSS  is  8 percent!!  "})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == [str(p)]


def test_token_overlap_paraphrase_flagged(tmp_path):
    # same tokens plus one extra word, no exact or normalized equality.
    p = write(tmp_path, "a.json",
              {"note": "my stop loss is 8 percent, roughly"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == [str(p)]


def test_nested_artifact_strings_scanned(tmp_path):
    p = write(tmp_path, "a.json",
              {"items": [{"memo": "My stop-loss is 8 percent"}]})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == [str(p)]


def test_unrelated_artifact_not_flagged(tmp_path):
    p = write(tmp_path, "a.json",
              {"note": "quarterly planning notes", "task": "general-qa"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == []


def test_short_strings_do_not_trigger_token_overlap(tmp_path):
    # two tokens: only exact or normalized equality may flag, not overlap
    p = write(tmp_path, "a.json", {"note": "stop loss"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == []


def test_unreadable_artifact_is_a_hard_error(tmp_path):
    p = write(tmp_path, "broken.json", "not json at all {{{")
    with pytest.raises(ArtifactError) as ei:
        find_bad_artifacts(TEST_CASES, [str(p)])
    assert str(p) in str(ei.value)


def test_missing_artifact_file_is_a_hard_error(tmp_path):
    missing = tmp_path / "absent.json"
    with pytest.raises(ArtifactError) as ei:
        find_bad_artifacts(TEST_CASES, [str(missing)])
    assert "absent.json" in str(ei.value)


def test_run_eval_fails_closed_on_unreadable_artifact(tmp_path, capsys):
    bad = tmp_path / "thresholds" / "general-qa.json"
    bad.parent.mkdir()
    bad.write_text("{ this is not json")
    rc = run_eval(str(evalmod.CASES_FILE), task="general-qa",
                  registry_path=None, root=tmp_path)
    assert rc == 2
    out = capsys.readouterr().out
    assert "fails closed" in out and "general-qa.json" in out


def test_run_eval_fails_closed_on_missing_registry_artifact(tmp_path,
                                                           capsys):
    rc = run_eval(str(evalmod.CASES_FILE), task="general-qa",
                  registry_path=str(tmp_path / "gone.json"), root=tmp_path)
    assert rc == 2
    assert "fails closed" in capsys.readouterr().out


def test_run_eval_green_with_clean_artifacts(tmp_path, capsys):
    clean = tmp_path / "thresholds" / "general-qa.json"
    clean.parent.mkdir()
    clean.write_text(json.dumps({"task": "general-qa",
                                 "thresholds": {"admit.durable": 0.58}}))
    rc = run_eval(str(evalmod.CASES_FILE), task="general-qa",
                  registry_path=None, root=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "provenance=synthetic-rule" in out


def test_similarity_threshold_is_bounded():
    assert 0.5 <= CONTAMINATION_SIM <= 0.95
