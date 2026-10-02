# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

- `src/uncluttered_memory/gate.py` - one batch of typed judge questions, code enforces drop / quarantine / store. Unseen input fails closed to quarantine, never an exception. RuleJudge is an offline heuristic stub keyed by text features; it is not Jev. Every decision cutoff (confidence, play, sensitive, stop, durable, importance) is a parameter whose default lives in `thresholds.py`.
- `src/uncluttered_memory/thresholds.py` - the one home for every decision-threshold default. Logic paths read cutoffs from here; no other module hardcodes a numeric decision boundary. The per-task registry can override `admit.durable` only.
- `src/uncluttered_memory/console.py` - report streams are forced to UTF-8 with a named error handler (`backslashreplace`), so a cp1252 console or pipe never mangles a report line.
- `src/uncluttered_memory/store.py` - SQLite with content-hash dedupe (normalized text; the dead exact-text fallback branch was removed), provenance per row, soft tombstones (never rewrites), a real quarantine table, an unresolved-conflict table, and per-user scoping.
- `src/uncluttered_memory/supersede.py` - code-ordered candidate pairs, relation vote via the judge protocol (supersede / coexist / conflict_unresolved / unrelated). Only an agreed supersede soft-tombstones the old fact; an agreed clash marks both facts conflict_unresolved and keeps both live, never a tombstone. Named-human override for restore / retire.
- `src/uncluttered_memory/recall.py` - the read path: gate, band, and cap are parameters defaulting to `thresholds.py`; code packs.
- `src/uncluttered_memory/inject.py` - card-first packing, whole-card truncation, hard budget from `thresholds.py`.
- `src/uncluttered_memory/calibrate.py` - per-task threshold registry fingerprinted to the task name, refuses mismatched files, UNCALIBRATED default, train-only tuning.
- `src/uncluttered_memory/jev_client.py` - judge protocol with a native Jev client, plus the heterogeneous offline relation pair (StrictRelationJudge + LenientRelationJudge).
- `eval/run.py` - one-command eval over two case sets: the hand-authored golden set (the claim) and the synthetic bulk set (self-consistency). Per-suite tables, admit precision/recall/F1, latency, cost-per-1k estimate, contamination scans that fail closed.
- `eval/golden.jsonl` - 158 hand-authored cases written as data (text plus expected label), provenance `hand-authored`, sharing no code path with the stubs. This is where the headline numbers come from.
- `eval/cases.py` - deterministic generator for the bulk `eval/frozen.jsonl` only (provenance `synthetic-rule`). It never reads or writes the golden set.
- `scripts/live_spotcheck.py` - information-only live sample of 20 golden cases against `jev-1.13-free`.

Install and run:

    pip install -e .
    python3 -m pytest tests/
    unclutter run
    python3 scripts/live_spotcheck.py   # information only, skips without a key

The live Jev test runs only when `HERMES_CUSTOM_OPENCODE_AI_API_KEY` is
set; everything else is offline.

## Eval: golden is the claim, bulk is self-consistency

Two case sets, two jobs, reported separately on every run:

- **Golden (`eval/golden.jsonl`, provenance `hand-authored`).** Cases
  written by hand as data: a text and the label a careful reader of the
  gate contract would give it, including tricky paraphrases and
  near-misses across all six gates (admit, importance, dedupe,
  contradict, supersede, rerank). The labels never come from stub code;
  the generator does not touch this file, and a test proves the two
  sets share no text. The runner refuses to start without it, refuses
  fewer than 120 cases, refuses any suite missing, and refuses any
  overlap with the bulk set. The headline numbers are the golden
  numbers.
- **Bulk (`eval/frozen.jsonl`, provenance `synthetic-rule`).** Templates
  and paraphrase variants whose labels are pinned to the documented
  stubs. This set is a self-consistency check of the frozen harness, not
  a benchmark claim, and the report labels it that way.

The final status line names both, golden first, for example:
`PASS: golden 0 failures, bulk 0 failures`. Exit code 1 means a golden
or bulk case failed (the headline is golden), 2 means the split,
provenance, golden, or contamination checks failed closed, 3 means the
Jev free window rate-limited and the run halted.

The report prints the case-file hash, the golden-file hash, the
provenance of both sets, and its own measured numbers on every run.

## Judge wiring

The judge protocol is Jev-shaped: typed calls (noul / choice / score)
that each return a verdict plus a confidence value. The offline stubs
(RuleJudge, FakeJudge, RuleRelationJudge, StrictRelationJudge,
LenientRelationJudge) are for unit tests and the offline eval only and
are never labeled as Jev.

Offline relation judging is heterogeneous by construction. Every
offline `decide()` call in the eval and the tests runs through
`offline_relation_pair()`: StrictRelationJudge (conservative, requires
a shared slot before accepting an update or a clash) paired with
LenientRelationJudge (permissive, marker-driven). The two genuinely
disagree on crafted near-misses (pinned in `tests/test_judge_pairs.py`),
so a destructive act only proceeds when two distinct readings agree; a
disagreement vetoes and keeps everything live. Two copies of one stub
used to agree by construction, and that theater is gone: a test shows
the copied pair would tombstone a case the heterogeneous pair vetoes.

`JevJudgeClient` talks native Jev at `https://opencode.ai/zen/v1/systemone`
with one model, `jev-1.13-free`, set via `UNCLUTTER_JEV_MODEL` (default
`jev-1.13-free`). It sends the request shape from the Tracky direct-mode
pattern (id-keyed `questions`, `state`, `answers`), reimplemented here in
Python. The API key comes from `HERMES_CUSTOM_OPENCODE_AI_API_KEY`, the
session header is `hermes-go-static-7f3a9c2e`.

There is no fallback model anywhere in this project. On HTTP 429 the
client raises `RateLimited` (with retry-after when present) and callers
halt with a plain message telling the operator the free window is
rate-limited. Pending items land in the quarantine table
(`Store.admit`), never voted by a stub, never redirected to another
model.

Response parsing is pinned by recorded native fixtures under
`tests/fixtures/` (replayed offline through the real parser; derived
failure variants are labeled as such in the fixtures README).

## Thresholds

Every decision cutoff lives in `src/uncluttered_memory/thresholds.py`
and every `Gate.decide` / `Recall.select` cutoff is a parameter
defaulting to it, so tests and calibration can override any of them
without touching logic. Reason strings echo the effective value (for
example `stop>=0.58`, or `stop>=0.9` when overridden). A test pins the
parametrization and checks that the logic modules contain no hardcoded
decision cutoff.

## Console encoding

`eval/run.py` and the CLI call `configure_console()`, which explicitly
reconfigures stdout and stderr to UTF-8 with `errors="backslashreplace"`.
A cp1252 console cannot mangle the report, and unencodable characters
degrade to visible escapes instead of mojibake or a crash. The success
line is pinned byte for byte by `tests/test_encoding.py`, including a
run under a forced cp1252 environment and a run whose case text carries
a non-ASCII character.

## Live spotcheck (information only)

`scripts/live_spotcheck.py` samples 20 golden cases deterministically
and asks live `jev-1.13-free` the same questions the offline stub
answers, then prints the stub-vs-live agreement rate. The rate gates
nothing: no test, eval, or CI depends on it. Without the API key the
script skips cleanly with no network calls. On HTTP 429 it halts
honestly with the rate-limit message, never falls back to another
model, and never lets a stub answer in Jev's place.

## Lifecycle and store honesty

`human_override` (restore / retire) and `Store.restore` are covered by
tests including override-then-read-back and restore-of-tombstone. The
exact-text fallback branch in `Store.put` was dead code (a row whose
text matches also carries the hash of that text) and was removed; the
dedupe contract is by normalized content hash only, pinned by tests.

## Honesty

No benchmark numbers are claimed for the bulk labels: they are
rule-generated (provenance `synthetic-rule`), not human labels, and
this README quotes none of the eval numbers. The headline numbers come
from the hand-authored golden set and are printed with both file hashes
on every run. Cost is marked ESTIMATE / NOT VERIFIED, and contamination
checks run before anything is scored (train/test disjointness by case
hash and normalized text, golden disjoint from bulk, artifacts fail
closed).
