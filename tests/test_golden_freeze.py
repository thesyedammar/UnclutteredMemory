"""Golden label freeze: the stub is changed to meet frozen labels.

The golden labels in eval/golden.jsonl are frozen as of 2026-10-02
(see eval/GOLDEN_CHANGELOG.md). The direction of fit is fixed: stub
code moves, labels do not. A label changes only for documented human
error, with a changelog entry carrying the case id, the old label,
the new label, a human reason, and a date. Label edits without an
entry fail this suite.

The last test reverses the burden: one label mutated in memory must
fail both the offline suite and the freeze check, proving the labels
drive the verdict instead of the verdict driving the labels.
"""
import json
import re
from pathlib import Path

from eval.run import (GOLDEN_CHANGELOG, GOLDEN_FROZEN_LABELS,
                      evaluate_suite, load_golden)
from uncluttered_memory.gate import Gate, RuleJudge

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.jsonl"

ENTRY_KINDS = ("label", "add", "remove")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _norm(v) -> str:
    return json.dumps(v, sort_keys=True)


def load_frozen_labels(path=GOLDEN_FROZEN_LABELS) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_changelog(path=GOLDEN_CHANGELOG) -> tuple:
    """Return (freeze_sha, entries). Fenced blocks never parse."""
    text = Path(path).read_text(encoding="utf-8")
    live = []
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            live.append(line)
    sha = None
    for line in live:
        m = re.search(r"`([0-9a-f]{64})`", line)
        if m:
            sha = m.group(1)
            break
    entries = []
    cur: dict = {}
    for line in live:
        m = re.match(r"^- (case|kind|old|new|date|reason):\s*(.*)$",
                     line.strip())
        if not m:
            if (cur and line.strip()
                    and (line.startswith((" ", "\t")))
                    and "reason" in cur):
                cur["reason"] += " " + line.strip().strip("`").strip()
            elif cur and line.strip() and not line.startswith((" ", "\t")):
                entries.append(cur)
                cur = {}
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "case" and cur:
            entries.append(cur)
            cur = {}
        val = val.strip("`").strip()
        if key == "reason":
            val = val.strip("`").strip()
        if key in ("old", "new") and val == "none":
            val = None
        cur[key] = val
    if cur:
        entries.append(cur)
    return sha, entries


def _entry_value(v):
    """Changelog old/new back to a label: ints stay ints."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def check_freeze(cases: list, frozen: dict, entries: list) -> list:
    """Undocumented golden drift. Returns violation strings, [] when clean.

    Added or removed case ids need kind=add/remove entries; changed
    labels need kind=label entries whose old matches the frozen map and
    whose new matches the live file. Every entry needs all five
    fields with a dated human reason.
    """
    violations = []
    current = {c["id"]: c["expect"] for c in cases}
    by_case: dict = {}
    for e in entries:
        problems = []
        if e.get("kind") not in ENTRY_KINDS:
            problems.append("bad kind %r" % e.get("kind"))
        if not e.get("case"):
            problems.append("missing case id")
        if not e.get("date") or not _DATE_RE.match(e["date"] or ""):
            problems.append("bad date %r" % e.get("date"))
        if not e.get("reason") or len(e["reason"]) < 20:
            problems.append("missing human reason")
        if e.get("kind") == "label" and (
                e.get("old") is None or e.get("new") is None):
            problems.append("label change needs old and new")
        if e.get("kind") == "add" and e.get("old") is not None:
            problems.append("add needs old none")
        if e.get("kind") == "remove" and e.get("new") is not None:
            problems.append("remove needs new none")
        if problems:
            violations.append("changelog entry for %r invalid: %s"
                              % (e.get("case"), "; ".join(problems)))
            continue
        by_case.setdefault(e["case"], []).append(e)

    for cid, exp in sorted(current.items()):
        if cid not in frozen:
            cov = [e for e in by_case.get(cid, [])
                   if e["kind"] == "add"
                   and _norm(_entry_value(e["new"])) == _norm(exp)]
            if not cov:
                violations.append(
                    "added case %r has no changelog add entry" % cid)
            continue
        if _norm(exp) != _norm(frozen[cid]):
            cov = [e for e in by_case.get(cid, [])
                   if e["kind"] == "label"
                   and _norm(_entry_value(e["old"])) == _norm(frozen[cid])
                   and _norm(_entry_value(e["new"])) == _norm(exp)]
            if not cov:
                violations.append(
                    "label change on %r (%s -> %s) has no matching "
                    "changelog entry" % (cid, frozen[cid], exp))
    for cid in sorted(frozen):
        if cid not in current:
            cov = [e for e in by_case.get(cid, [])
                   if e["kind"] == "remove"
                   and _norm(_entry_value(e["old"])) == _norm(frozen[cid])]
            if not cov:
                violations.append(
                    "removed case %r has no changelog remove entry" % cid)
    return violations


def test_changelog_exists_with_freeze_record():
    assert GOLDEN_CHANGELOG.exists()
    sha, entries = parse_changelog()
    assert sha is not None and re.fullmatch(r"[0-9a-f]{64}", sha)
    frozen = load_frozen_labels()
    assert len(frozen) == 160
    cases, err = load_golden(GOLDEN)
    assert err is None
    assert set(frozen) == {c["id"] for c in cases}


def test_no_undocumented_label_change_since_freeze():
    """Any label edit without a changelog entry fails the suite."""
    cases, err = load_golden(GOLDEN)
    assert err is None
    _, entries = parse_changelog()
    assert check_freeze(cases, load_frozen_labels(), entries) == []


def test_changelog_entries_all_schema_valid():
    _, entries = parse_changelog()
    assert entries == []
    headers = [ln for ln in GOLDEN_CHANGELOG.read_text(
        encoding="utf-8").splitlines() if ln.strip() == "## Changes"]
    assert len(headers) == 1


def test_mutated_label_fails_suite_and_freeze_check():
    """Burden reversal: labels drive the verdict, not the reverse."""
    cases, err = load_golden(GOLDEN)
    assert err is None
    target = next(c for c in cases if c["suite"] == "admit")
    flipped = ("DROP" if target["expect"] != "DROP" else "STORE")
    mutated = dict(target, expect=flipped)
    gate = Gate(RuleJudge())
    rows, _ = evaluate_suite("admit", [mutated], gate)
    assert len(rows) == 1
    assert not rows[0][3], (
        "mutated label %r must fail the offline suite" % flipped)
    drifted = [mutated if c["id"] == target["id"] else c for c in cases]
    _, entries = parse_changelog()
    bad = check_freeze(drifted, load_frozen_labels(), entries)
    assert bad, "undocumented label change must fail the freeze check"
    assert any(target["id"] in v for v in bad)


def test_bad_changelog_entry_is_rejected():
    cases, err = load_golden(GOLDEN)
    assert err is None
    frozen = load_frozen_labels()
    target = next(c for c in cases if c["suite"] == "admit")
    old = frozen[target["id"]]
    new = "DROP" if old != "DROP" else "STORE"
    changed = [dict(c, expect=new) if c["id"] == target["id"] else c
               for c in cases]
    base = {"case": target["id"], "kind": "label", "old": old,
            "new": new, "date": "2026-10-03",
            "reason": "a careful contract reading gives %s here" % new}
    assert check_freeze(changed, frozen, [dict(base)]) == []
    assert check_freeze(changed, frozen,
                        [dict(base, reason="too short")]) != []
    assert check_freeze(changed, frozen,
                        [dict(base, date="tomorrow")]) != []
    assert check_freeze(changed, frozen,
                        [dict(base, old="WRONG-LABEL")]) != []
    assert check_freeze(changed, frozen, []) != []
