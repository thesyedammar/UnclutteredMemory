"""Calibration output must never land in the eval scan tree.

Round-3 finding (footgun): `unclutter calibrate` defaulted its output
into the repo `thresholds/` directory, which the next `unclutter run`
scans as a tuning artifact. A stale or malformed file there can fail
the run closed, and any artifact that touches the test split makes
the run refuse to score at all.

The fix has three parts, all pinned here:

1. The default output path is the operator's current working
   directory (outside the repo scan tree), never `thresholds/` or
   `eval/thresholds*`.
2. `is_scanned_output_path` classifies those in-tree paths so an
   explicit `--out` there warns loudly.
3. The exact scenario is tested end to end: calibrate with the
   default, then run the eval, and the run stays green with the repo
   scan tree untouched. A crafted artifact inside the scan tree still
   fails the run closed (loud, never silent).
"""
import json

from uncluttered_memory import calibrate as calmod
from uncluttered_memory import cli as climod

from eval.run import default_artifact_paths, run_eval


def test_default_calibration_out_is_outside_the_repo_scan_tree(tmp_path,
                                                               monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = climod.default_calibration_out("general-qa")
    assert out == str(tmp_path / "general-qa.thresholds.json")
    assert not climod.is_scanned_output_path(out)


def test_scanned_path_detection_pins_the_old_footgun():
    repo = climod.REPO
    # the exact old default: repo thresholds/<task>.json
    assert climod.is_scanned_output_path(repo / "thresholds" / "general-qa.json")
    # any extension the scan walks in thresholds/
    assert climod.is_scanned_output_path(repo / "thresholds" / "notes.yaml")
    # eval/thresholds* siblings the scan also walks
    assert climod.is_scanned_output_path(repo / "eval" / "thresholds.json")
    assert climod.is_scanned_output_path(repo / "eval" / "thresholds-live.yaml")
    # outside the tree is clean
    assert not climod.is_scanned_output_path("/tmp/general-qa.thresholds.json")


def test_calibrate_then_run_stays_green_exact_scenario(tmp_path, monkeypatch,
                                                       capsys):
    """Calibrate with the default, then run: green, repo tree untouched."""
    monkeypatch.chdir(tmp_path)
    rc = climod.main(["calibrate", "--task", "general-qa"])
    assert rc == 0
    out = tmp_path / "general-qa.thresholds.json"
    assert out.exists()
    assert "WARNING" not in capsys.readouterr().out
    # The repo scan tree gained nothing.
    assert not (climod.REPO / "thresholds" / out.name).exists()
    # And the exact scenario: the next run stays green.
    rc = run_eval()
    report = capsys.readouterr().out
    assert rc == 0, report
    assert "PASS" in report
    assert "CONTAMINATION" not in report


def test_warning_fires_when_out_points_into_the_scan_tree(tmp_path,
                                                          monkeypatch,
                                                          capsys):
    monkeypatch.setattr(climod, "REPO", tmp_path)
    out = tmp_path / "thresholds" / "general-qa.json"
    climod.warn_if_scanned_output(str(out))
    printed = capsys.readouterr().out
    assert "WARNING" in printed
    assert "scanned" in printed and "thresholds/" in printed
    # outside the tree: no warning
    climod.warn_if_scanned_output(str(tmp_path / "outside.json"))
    assert "WARNING" not in capsys.readouterr().out


def test_calibrate_with_out_inside_the_tree_warns_and_still_writes(
        tmp_path, monkeypatch, capsys):
    """An explicit --out into the tree is honoured, with a loud warning."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setattr(climod, "REPO", fake_repo)
    monkeypatch.chdir(tmp_path)
    out = fake_repo / "thresholds" / "general-qa.json"
    rc = climod.main(["calibrate", "--task", "general-qa", "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "WARNING" in printed
    assert out.exists()
    assert json.loads(out.read_text())["task"] == "general-qa"


def test_conformal_with_out_inside_the_tree_warns(tmp_path, monkeypatch,
                                                  capsys):
    """The conformal command warns on the eval/thresholds* path too."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    monkeypatch.setattr(climod, "REPO", fake_repo)
    monkeypatch.chdir(tmp_path)
    out = fake_repo / "eval" / "thresholds-general-qa.json"
    rc = climod.main(["conformal", "--task", "general-qa", "--gate",
                      "admit", "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "WARNING" in printed
    assert out.exists()


def test_artifact_inside_the_scan_tree_fails_the_run_closed(tmp_path,
                                                            capsys):
    """The failure mode the fix avoids: a bad file in the tree is loud.

    run_eval scans root/thresholds/*.json. A malformed file there is a
    hard ArtifactError: the run refuses to score (exit 2), never
    silently skips the target.
    """
    fake_root = tmp_path / "repo"
    (fake_root / "thresholds").mkdir(parents=True)
    (fake_root / "thresholds" / "general-qa.json").write_text(
        "{not json", encoding="utf-8")
    listed = default_artifact_paths(fake_root)
    assert str(fake_root / "thresholds" / "general-qa.json") in listed
    rc = run_eval(root=fake_root)
    report = capsys.readouterr().out
    assert rc == 2, report
    assert "CONTAMINATION" in report and "fails closed" in report


def test_calibrate_gate_artifact_in_scan_tree_is_seen_by_the_scan(tmp_path):
    """A real calibration artifact written into the tree is listed."""
    fake_root = tmp_path / "repo"
    (fake_root / "thresholds").mkdir(parents=True)
    out = fake_root / "thresholds" / "general-qa.json"
    calmod.calibrate_gate(
        [{"text": "keep the 8% stop", "expect": "STORE"},
         {"text": "lol", "expect": "DROP"}], "general-qa", str(out),
        lambda c: 0.9 if c["expect"] == "STORE" else 0.1)
    assert str(out) in default_artifact_paths(fake_root)
