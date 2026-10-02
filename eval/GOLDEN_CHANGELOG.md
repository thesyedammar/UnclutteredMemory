# Golden label freeze (2026-10-02)

The golden labels in `eval/golden.jsonl` are FROZEN as of 2026-10-02
at commit `4375f92` (harsh-judge round 12).

## Policy

The direction of fit is fixed: the STUB is changed to meet the frozen
labels; the labels are never rewritten to satisfy the scorer. A golden
label changes only for documented HUMAN error (a careful reader of the
gate contract would not give that label), never to make the offline
system pass. Every change needs an entry below, and the suite fails
without one (see `tests/test_golden_freeze.py`).

Freeze provenance:

- `golden.jsonl` sha256 at freeze:
  `350d544a57069cb6c62998e9f387b30b2415c138f4368e0a0620d558daa73d3f`
- Frozen label map: `eval/golden_labels_frozen.json` (160 case ids to
  their frozen `expect` values). The freeze test diffs the live
  `golden.jsonl` against this map.
- Census at freeze: 160 cases (admit 56, importance 24, dedupe 20,
  contradict 23, supersede 23, rerank 14).

## Entry schema

Each change is one block under `## Changes` with all five fields:

- `case:` the golden case id (for example `g-admit-0007`)
- `kind:` one of `label` (expect changed), `add` (case added),
  `remove` (case removed)
- `old:` the frozen label, or `none` for `add`
- `new:` the current label, or `none` for `remove`
- `date:` YYYY-MM-DD
- `reason:` one human sentence naming the contract reading that makes
  the old label an error (no scorer talk: never "so the stub passes")

Example (illustrative only, never parsed as a real entry):

```
- case: `g-admit-0007`
- kind: `label`
- old: `STORE`
- new: `DROP`
- date: `2026-10-03`
- reason: `the text is a bare acknowledgment with no durable content,
  so the gate contract reads DROP; the frozen STORE was a human slip.`
```

## Changes

No entries. No golden label has changed since the freeze.
