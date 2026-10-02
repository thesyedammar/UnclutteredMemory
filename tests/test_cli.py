"""CLI tests (round-3 findings): every human_override action is
documented in the help and exercised end to end (including tombstone,
which was accepted but undocumented), and `unclutter run` forwards
--registry to the eval runner."""
import json

import pytest

from uncluttered_memory import cli as climod
from uncluttered_memory.store import Store


def _make_db(tmp_path):
    db = tmp_path / "memory.db"
    s = Store(str(db))
    old = s.put("meeting is at 3pm", "user")
    new = s.put("meeting is at 4pm", "user")
    return db, old, new


def test_cli_override_restore_reads_back(tmp_path, capsys):
    db, old, new = _make_db(tmp_path)
    Store(str(db)).tombstone(old, new, "supersede-agreed", "code")
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "restore"])
    assert rc == 0
    assert "restore by human" in capsys.readouterr().out
    row = Store(str(db)).get(old)
    assert row[4] is None and row[5] is None and row[6] is None


def test_cli_override_retire_reads_back(tmp_path, capsys):
    db, old, new = _make_db(tmp_path)
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "retire", "--target-id", str(new),
                      "--reason", "user said so"])
    assert rc == 0
    assert "retire ->" in capsys.readouterr().out
    row = Store(str(db)).get(old)
    assert row[4] == new and row[5] == "user said so" and row[6] == "human"


def test_cli_override_tombstone_reads_back(tmp_path, capsys):
    """The action that used to be undocumented: explicit alias of retire."""
    db, old, new = _make_db(tmp_path)
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "tombstone", "--target-id", str(new)])
    assert rc == 0
    assert "tombstone ->" in capsys.readouterr().out
    row = Store(str(db)).get(old)
    assert row[4] == new and row[5] == "human-tombstone"
    assert row[6] == "human"
    assert [t for _, t, _ in Store(str(db)).live()] == ["meeting is at 4pm"]


def test_cli_override_help_documents_every_action(capsys):
    with pytest.raises(SystemExit) as ei:
        climod.main(["override", "--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for action in ("restore", "retire", "tombstone"):
        assert action in out
    assert "clear the tombstone fields" in out
    assert "soft-tombstone" in out
    assert "alias of retire" in out


def test_cli_override_retire_requires_target(tmp_path, capsys):
    db, old, new = _make_db(tmp_path)
    rc = climod.main(["override", "--db", str(db), "--fact-id", str(old),
                      "--action", "retire"])
    assert rc == 2
    assert "override refused" in capsys.readouterr().out
    assert Store(str(db)).get(old)[4] is None


def test_cli_override_unknown_fact_refused(tmp_path, capsys):
    db, old, new = _make_db(tmp_path)
    rc = climod.main(["override", "--db", str(db), "--fact-id", "999",
                      "--action", "restore"])
    assert rc == 2
    assert "no fact 999" in capsys.readouterr().out


def test_cli_run_forwards_registry_flag(monkeypatch):
    """`unclutter run --registry` must reach the eval runner's argv."""
    captured = {}

    class FakeEval:
        @staticmethod
        def main(argv):
            captured["argv"] = argv
            return 0

    monkeypatch.setattr(climod, "_eval", lambda: FakeEval)
    rc = climod.main(["run", "--task", "alpha",
                      "--registry", "/tmp/reg.json"])
    assert rc == 0
    assert captured["argv"] == ["--task", "alpha",
                                "--registry", "/tmp/reg.json"]


def test_cli_run_registry_flag_reaches_the_eval(tmp_path, capsys):
    """End to end: the forwarded registry is actually loaded."""
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"task": "alpha", "fingerprint": "x",
                               "thresholds": {"admit.durable": 0.58}}))
    rc = climod.main(["run", "--task", "beta", "--registry", str(reg)])
    assert rc == 2
    assert "registry error" in capsys.readouterr().out
