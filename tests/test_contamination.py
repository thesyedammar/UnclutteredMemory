"""Contamination checks: fail closed on unreadable artifacts, catch
paraphrased leaks via normalized comparison and token overlap, and
carry a machine-readable reason on every flag.

Round-3 finding: flags were bare file paths, so a report said a file
was bad without saying which check fired. Every flag is now a dict
(path, check, score, excerpt) returned by find_bad_artifacts and
printed by the report.

An artifact that cannot be parsed is a hard ArtifactError that lists
the file; the scan never silently skips a target.
"""
import json

import pytest

from eval import run as evalmod
from eval.run import (ArtifactError, CONTAMINATION_SIM, find_bad_artifacts,
                      format_artifact_flag, run_eval, split_cases,
                      text_hash)

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


def test_exact_string_touch_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"note": "my stop loss is 8 percent"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    f = flags[0]
    assert f["path"] == str(p)
    assert f["check"] == "exact-text"
    assert f["score"] == 1.0
    assert f["excerpt"] == "my stop loss is 8 percent"


def test_normalized_paraphrase_flagged_with_reason(tmp_path):
    # casefold + punctuation strip + whitespace collapse make this equal
    # to the test text only after normalization.
    p = write(tmp_path, "a.json",
              {"note": "  My  STOP-LOSS  is  8 percent!!  "})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    f = flags[0]
    assert f["check"] == "normalized-text"
    assert f["score"] == 1.0
    assert f["excerpt"] == "My STOP-LOSS is 8 percent!!"


def test_token_overlap_paraphrase_flagged_with_score(tmp_path):
    # same tokens plus one extra word, no exact or normalized equality.
    p = write(tmp_path, "a.json",
              {"note": "my stop loss is 8 percent, roughly"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    f = flags[0]
    assert f["check"] == "token-overlap"
    assert f["score"] >= CONTAMINATION_SIM
    assert f["score"] < 1.0
    assert "stop loss is 8 percent" in f["excerpt"]


def test_content_hash_embedding_flagged_with_reason(tmp_path):
    leak = text_hash("my stop loss is 8 percent")
    p = write(tmp_path, "a.json", {"leak": leak})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    f = flags[0]
    assert f["check"] == "content-hash"
    assert f["score"] == 1.0
    assert f["excerpt"] == leak


def test_split_field_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"task": "general-qa", "split": "test"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    f = flags[0]
    assert f["check"] == "split-field"
    assert f["score"] is None
    assert f["excerpt"] == "split=test"


def test_tuned_on_field_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"task": "general-qa",
                                   "tuned_on": "test"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "tuned_on=test"


def test_trained_on_field_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"task": "general-qa",
                                   "trained_on": "test"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "trained_on=test"


def test_train_on_field_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"task": "general-qa",
                                   "train_on": "test"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "train_on=test"


def test_fitted_on_field_flagged_with_reason(tmp_path):
    p = write(tmp_path, "a.json", {"task": "general-qa",
                                   "fitted_on": "test"})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "fitted_on=test"


def test_nested_artifact_strings_scanned(tmp_path):
    p = write(tmp_path, "a.json",
              {"items": [{"memo": "My stop-loss is 8 percent"}]})
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "normalized-text"
    assert flags[0]["excerpt"] == "My stop-loss is 8 percent"


def test_unrelated_artifact_not_flagged(tmp_path):
    p = write(tmp_path, "a.json",
              {"note": "quarterly planning notes", "task": "general-qa"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == []


def test_short_strings_do_not_trigger_token_overlap(tmp_path):
    # two tokens: only exact or normalized equality may flag, not overlap
    p = write(tmp_path, "a.json", {"note": "stop loss"})
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == []


def test_format_flag_line_carries_check_score_and_excerpt(tmp_path):
    p = write(tmp_path, "a.json",
              {"note": "my stop loss is 8 percent, roughly"})
    line = format_artifact_flag(find_bad_artifacts(TEST_CASES, [str(p)])[0])
    assert line.startswith(str(p))
    assert "check=token-overlap" in line
    assert "score=0." in line
    assert "excerpt=" in line and "stop loss" in line


def test_run_eval_report_prints_flag_reasons(tmp_path, capsys):
    with open(evalmod.CASES_FILE) as f:
        cases = [json.loads(line) for line in f if line.strip()]
    _, test = split_cases(cases)
    sample = next(c for c in test if "text" in c)
    bad = tmp_path / "thresholds" / "general-qa.json"
    bad.parent.mkdir()
    bad.write_text(json.dumps({"task": "general-qa",
                               "trained_on": sample["text"]}))
    rc = run_eval(str(evalmod.CASES_FILE), task="general-qa",
                  registry_path=None, root=tmp_path)
    assert rc == 2
    out = capsys.readouterr().out
    assert "CONTAMINATION" in out
    assert "check=exact-text" in out
    assert "score=1.000" in out
    assert "excerpt=" in out
    assert str(bad) in out


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


TEXT_EXTS = ("yaml", "yml", "toml", "txt", "md")


@pytest.mark.parametrize("ext", TEXT_EXTS)
def test_text_artifact_split_field_flagged_per_extension(tmp_path, ext):
    p = tmp_path / ("tuning." + ext)
    p.write_text("task: general-qa\nsplit: test\n", encoding="utf-8")
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "split=test"


@pytest.mark.parametrize("ext", TEXT_EXTS)
def test_text_artifact_toml_style_split_field_flagged(tmp_path, ext):
    p = tmp_path / ("tuning." + ext)
    p.write_text('task = "general-qa"\ntrained_on = "test"\n',
                 encoding="utf-8")
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "split-field"
    assert flags[0]["excerpt"] == "trained_on=test"


@pytest.mark.parametrize("ext", TEXT_EXTS)
def test_text_artifact_test_excerpt_flagged_per_extension(tmp_path, ext):
    p = tmp_path / ("notes." + ext)
    p.write_text("# tuning notes\nmy stop loss is 8 percent\n",
                 encoding="utf-8")
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "exact-text"
    assert flags[0]["excerpt"] == "my stop loss is 8 percent"


@pytest.mark.parametrize("ext", TEXT_EXTS)
def test_text_artifact_normalized_excerpt_flagged_per_extension(
        tmp_path, ext):
    p = tmp_path / ("notes." + ext)
    p.write_text("My STOP-LOSS is 8 percent\n", encoding="utf-8")
    flags = find_bad_artifacts(TEST_CASES, [str(p)])
    assert len(flags) == 1
    assert flags[0]["check"] == "normalized-text"


@pytest.mark.parametrize("ext", TEXT_EXTS)
def test_clean_text_artifact_not_flagged_per_extension(tmp_path, ext):
    p = tmp_path / ("clean." + ext)
    p.write_text("task: general-qa\nnotes: quarterly planning\n",
                 encoding="utf-8")
    assert find_bad_artifacts(TEST_CASES, [str(p)]) == []


def test_missing_text_artifact_is_a_hard_error(tmp_path):
    missing = tmp_path / "absent.txt"
    with pytest.raises(ArtifactError) as ei:
        find_bad_artifacts(TEST_CASES, [str(missing)])
    assert "absent.txt" in str(ei.value)


def test_default_paths_include_text_tuning_artifacts(tmp_path):
    from eval.run import default_artifact_paths
    (tmp_path / "thresholds").mkdir()
    (tmp_path / "eval").mkdir()
    wanted = {"notes.yaml": "thresholds", "tune.yml": "thresholds",
              "tune.toml": "thresholds", "notes.txt": "thresholds",
              "thresholds-notes.md": "eval"}
    for name, sub in wanted.items():
        (tmp_path / sub / name).write_text("clean notes\n",
                                           encoding="utf-8")
    (tmp_path / "eval" / "thresholds-notes.md").write_text(
        "clean notes\n", encoding="utf-8")
    paths = default_artifact_paths(tmp_path)
    for name in ("notes.yaml", "tune.yml", "tune.toml", "notes.txt",
                 "notes.md", "thresholds-notes.md"):
        assert any(str(tmp_path) in p and p.endswith(name) for p in paths), \
            (name, paths)
