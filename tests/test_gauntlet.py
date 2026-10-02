"""Gauntlet tests: every attack family fails closed, offline.

Five families (prompt injection, paraphrase exfil, tombstone
evasion, scope confusion, quota exhaustion) must quarantine or deny,
never admit. The quota attack replays a 429, it never hits the
network. `unclutter redteam` fires the same gauntlet end to end.
"""
import urllib.error

from uncluttered_memory import cli as climod
from uncluttered_memory.gate import Gate, RuleJudge
from uncluttered_memory.store import Store

from eval.gauntlet import (ATTACKS, PROMPT_INJECTION_TEXTS,
                           attack_paraphrase_exfil,
                           attack_prompt_injection,
                           attack_quota_exhaustion,
                           attack_scope_confusion,
                           attack_tombstone_evasion,
                           run_gauntlet)


def test_gauntlet_covers_five_attack_families():
    names = sorted(fn.__name__ for fn in ATTACKS)
    assert names == sorted((
        "attack_prompt_injection",
        "attack_paraphrase_exfil",
        "attack_tombstone_evasion",
        "attack_scope_confusion",
        "attack_quota_exhaustion",
    ))


def test_prompt_injection_never_stores():
    r = attack_prompt_injection()
    assert r["attack"] == "prompt_injection"
    assert r["passed"] is True
    gate = Gate(RuleJudge())
    for text in PROMPT_INJECTION_TEXTS:
        assert gate.decide(text, [], []).action in (
            "QUARANTINE", "DROP"), text
    assert r["live_guarded"] is True


def test_prompt_injection_admit_path_quarantines_or_drops():
    for text in PROMPT_INJECTION_TEXTS:
        s = Store()
        action = s.admit(text, "attacker", Gate(RuleJudge()))
        assert action in ("QUARANTINE", "DROP"), text
        assert [t for _, t, _ in s.live()] == []


def test_paraphrase_exfil_is_flagged(tmp_path):
    r = attack_paraphrase_exfil(str(tmp_path))
    assert r["attack"] == "paraphrase_exfil"
    assert r["passed"] is True
    assert len(r["flags"]) == 1
    assert r["flags"][0]["check"] in (
        "exact-text", "normalized-text", "token-overlap", "content-hash")


def test_tombstone_evasion_vetoes_to_keep():
    r = attack_tombstone_evasion()
    assert r["attack"] == "tombstone_evasion"
    assert r["passed"] is True
    assert r["action"] == "KEEP"


def test_scope_confusion_refused():
    r = attack_scope_confusion()
    assert r["attack"] == "scope_confusion"
    assert r["passed"] is True
    assert r["refused"] is True


def test_quota_exhaustion_quarantines_never_fabricates():
    r = attack_quota_exhaustion()
    assert r["attack"] == "quota_exhaustion"
    assert r["passed"] is True
    assert r["raised_429"] is True
    assert r["admit"] == "QUARANTINE"


def test_run_gauntlet_all_fail_closed():
    results, ok = run_gauntlet()
    assert len(results) == 5
    assert ok is True
    assert all(r["passed"] for r in results)


def test_cli_redteam_fires_the_gauntlet(capsys):
    rc = climod.main(["redteam"])
    assert rc == 0
    out = capsys.readouterr().out
    for name in ("prompt_injection", "paraphrase_exfil",
                 "tombstone_evasion", "scope_confusion",
                 "quota_exhaustion"):
        assert name in out
    assert "REDTEAM PASS" in out
