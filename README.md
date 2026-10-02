# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

## Quickstart

    pip install -e .
    python3 -m pytest tests/          # offline suite, no key needed
    unclutter run                     # frozen eval: conformance + self-consistency
    python3 playground/demo.py        # six-line offline tour of every verdict
    unclutter serve --db memory.db --port 8765   # HTTP over the real store

The live Jev check runs only when `HERMES_CUSTOM_OPENCODE_AI_API_KEY`
is set; everything else is offline.

## Honesty: what the numbers are

- **Contract conformance (golden, hand-authored): 160/160.** How
  often the offline stub's reading matches the frozen human reading
  of the gate contract. NOT accuracy, NOT memory quality.
- **Paid rubric (`jev-1.13`, live): importance 20/24 = 83.3%,
  admit 40/56 = 71.4%.** Live-vs-label on the golden set with the
  rubric prompt (see `docs/calibration-20261002-114232-rubric.md`).
  Paid-key runs only; never a repo default.
- **Free tier (`jev-1.13-free`, live): 10/24 = 41.7%.**
  Independent-rater agreement with the golden labels, varies run to
  run (see `docs/label-audit-20261002.md`). Information only; it
  gates nothing.
- **Limits.** Recall matches surface wording, not deep paraphrase;
  the strongest importance-independence bound (feature pairs/triples)
  is exceeded on the current labels and flagged for human review
  (`eval/GOLDEN_CHANGELOG.md`); cost figures are ESTIMATE / NOT
  VERIFIED. No benchmark numbers are claimed for the synthetic bulk
  set (self-consistency only).

- `src/uncluttered_memory/gate.py` - one batch of typed judge questions, code enforces drop / quarantine / store. Unseen input fails closed to quarantine, never an exception. RuleJudge is an offline heuristic stub keyed by text features; it is not Jev. Every decision cutoff (confidence, play, sensitive, stop, durable, importance) is a parameter whose default lives in `thresholds.py`.
- `src/uncluttered_memory/thresholds.py` - the one home for every decision-threshold default and every RuleJudge vote level. Logic paths read cutoffs from here; no other module hardcodes a numeric decision boundary or vote literal. The per-task registry can override `admit.durable` only.
- `src/uncluttered_memory/console.py` - report streams are forced to UTF-8 with a named error handler (`backslashreplace`), so a cp1252 console or pipe never mangles a report line.
- `src/uncluttered_memory/store.py` - SQLite with two-stage dedupe (exact normalized content hash first, then token-set Jaccard at `DEDUP_JACCARD` = 0.85 over live same-user rows; the dead exact-text fallback branch was removed), provenance per row, soft tombstones (never rewrites), a real quarantine table, an unresolved-conflict table, and per-user scoping. `Store.admit` quarantines only judge-halt exceptions (the JevError family: rate limit, bad key, transport, malformed judge answer); any other exception is a coding bug that increments an explicit `error_count`, emits one structured log line (time, op, input hash, error type), and propagates instead of vanishing as a quarantine.
- `src/uncluttered_memory/supersede.py` - code-ordered candidate pairs, relation vote via the judge protocol (supersede / coexist / conflict_unresolved / unrelated). Only an agreed supersede soft-tombstones the old fact; an agreed clash marks both facts conflict_unresolved and keeps both live, never a tombstone. Named-human override for restore / retire / tombstone, each documented in the CLI help (`unclutter override --help`) and tested end to end.
- `src/uncluttered_memory/recall.py` - the read path: gate, band, and cap are parameters defaulting to `thresholds.py`; code packs.
- `src/uncluttered_memory/inject.py` - card-first packing, whole-card truncation, hard budget from `thresholds.py`.
- `src/uncluttered_memory/calibrate.py` - per-task threshold registry fingerprinted to the task name, refuses mismatched files, UNCALIBRATED default, train-only tuning.
- `src/uncluttered_memory/jev_client.py` - judge protocol with a native Jev client, plus the heterogeneous offline relation pair (StrictRelationJudge + LenientRelationJudge). StrictRelationJudge requires at least two shared content tokens beyond stopwords and numbers before it reads a marker as being about the same slot.
- `eval/run.py` - one-command eval over two case sets: the hand-authored golden set (the claim) and the synthetic bulk set (self-consistency). Per-suite tables, admit precision/recall/F1, latency, cost-per-1k estimate, contamination scans that fail closed. Every contamination flag carries a machine-readable reason (which check fired, similarity score, offending excerpt) and the report prints it.
- `eval/golden.jsonl` - 160 hand-authored cases written as data (text plus expected label), provenance `hand-authored`, sharing no code path with the stubs. This is where the contract-conformance numbers come from: the number measures stub-vs-frozen-human-reading (how often the offline stub's reading matches the frozen human reading of the gate contract), NOT accuracy and NOT memory quality.
- `eval/golden_labels_frozen.json` - the frozen label map (case id to frozen label), pinned at the 2026-10-02 freeze.
- `eval/GOLDEN_CHANGELOG.md` - the freeze record (file hash, census, policy). A golden label changes only for documented human error with an entry here; undocumented edits fail the suite (`tests/test_golden_freeze.py`).
- `eval/cases.py` - deterministic generator for the bulk `eval/frozen.jsonl` only (provenance `synthetic-rule`). It never reads or writes the golden set.
- `scripts/live_spotcheck.py` - information-only live sample of 20 golden cases against `jev-1.13-free`. On full completion with the key present it refreshes `tests/fixtures/live_votes_20261002.json` (recorded live votes plus metadata), which the offline ratchet test reads; `--no-record` disables the refresh.

Install and run:

    pip install -e .
    python3 -m pytest tests/
    unclutter run
    unclutter override --help   # restore | retire | tombstone
    python3 scripts/live_spotcheck.py   # information only, skips without a key

The live Jev test runs only when `HERMES_CUSTOM_OPENCODE_AI_API_KEY` is
set; everything else is offline.

## Eval: golden is contract conformance, bulk is self-consistency

Two case sets, two jobs, reported separately on every run. The golden
number is contract conformance: it measures
stub-vs-frozen-human-reading, how often the offline stub's reading
matches the frozen human reading of the gate contract. It is NOT
accuracy and NOT memory quality. Beside it, every
run prints the independent-rater number: recorded live
`jev-1.13-free` votes against the golden labels, 10/24 = 41.7% on
2026-10-02 (see `docs/label-audit-20261002.md`). Live Jev is an
independent rater that agrees less than half the time and varies run
to run; neither number gates the other.

- **Golden (`eval/golden.jsonl`, provenance `hand-authored`).** Cases
  written by hand as data: a text and the label a careful reader of the
  gate contract would give it, including tricky paraphrases and
  near-misses across all six gates (admit, importance, dedupe,
  contradict, supersede, rerank). The labels never come from stub code;
  the generator does not touch this file, and a test proves the two
  sets share no text. The runner refuses to start without it, refuses
  fewer than 120 cases, refuses any suite missing, refuses any suite
  below its per-suite floor (admit 40, importance 15, dedupe 12,
  contradict 12, supersede 12, rerank 8), and refuses any
  overlap with the bulk set. The current census is 160 cases: admit
  56, importance 24, dedupe 20, contradict 23, supersede 23, rerank
  14, pinned exactly by `tests/test_golden.py`. The conformance
  numbers are the golden numbers, and the labels are frozen (see
  `eval/GOLDEN_CHANGELOG.md`): the stub is changed to meet them,
  a label changes only for documented human error with a changelog
  entry, never to satisfy the scorer.
- **Bulk (`eval/frozen.jsonl`, provenance `synthetic-rule`).** Templates
  and paraphrase variants whose labels are pinned to the documented
  stubs. This set is a self-consistency check of the frozen harness, not
  a benchmark claim, and the report labels it that way.

Golden independence, stated plainly. The admit, dedupe, contradict,
supersede, and rerank golden suites are fully independent of the
stubs: their labels were written from the gate contract, they share
no code path with `eval/cases.py`, and a test proves the two sets
share no text. The importance suite was not: an earlier version
mirrored the stub buckets (every 5 carried a hard marker token),
so the hand-authored claim was overstated there. That suite has
been rewritten from human judgment of what is actually worth
remembering, deliberately breaking the buckets: vital facts with
no marker words, trivial facts carrying marker words, and
near-boundary judgments. Four checks pin it:
`tests/test_importance_independence.py` proves labels live in the
data file (stripping every marker token leaves stored labels
unchanged while a stub-mimicking marker predictor misses widely),
proves a coarse marker-only classifier trained on half the suite
cannot reproduce the held-out labels (accuracy under 0.7), and
proves the same at full resolution with a mirror-image classifier
that extracts the FULL stub feature set (every list and signal the
offline scorer reads, taken from the scorer's own lists and
predicates) under the same strict 0.7 bound; it also proves the
offline scorer earns at least 3 marker-free vitals and at least 3
marker-bearing trivials. The scoring signals are documented as
compositional pairings in `gate.py`, not marker lists. A label set
tuned against the stub would score high on the mirror-image split
and fail the test, so such a failure means the scoring signals must
change, not the labels: labels are frozen and move only through a
changelogged human-error correction (`eval/GOLDEN_CHANGELOG.md`),
never to satisfy the scorer.

A fifth check, the strongest of them, is EXCEEDED on the current
labels, stated plainly. An exhaustive conjunction search over all
feature pairs (231) and triples (1540) of the full 22-signal set,
trained on the even rows and scored on the held-out odd rows, reaches
9/12 = 0.75 (best pair) and 10/12 = 0.833 (best triple), both above
the 0.7 bound and above the fixed-seed label-permutation null (best
pair 9/12 four times in 1000 permutations, best triple never above
9/12), so the exceedance is genuine structure, not selection noise.
Root cause: the direction of fit is fixed (the stub is changed to
meet the frozen labels) and the stub reproduces every importance
label exactly, which makes the labels a function of the tuned
scorer's signals by construction; any learner strong enough to
approximate the tuned scorer's categories (vital, routine) exceeds
the bound at pair resolution. This does not show the labels were
derived from the stub at authoring time, and it does not show the
labels are wrong; it does mean the independence claim is NOT made at
pair or triple resolution, and per the changelog flow the exceedance
reveals pair-level derivability of the frozen labels from the tuned
scorer's signals and the labels need human review
(`eval/GOLDEN_CHANGELOG.md`). The two checks are strict xfails
(`tests/test_importance_independence.py`): they fail today, and they
flip to failures if a changelogged review ever makes the bound hold,
so nothing resolves silently.

The report prints two numbers on every run, golden first: contract
conformance (`CONTRACT CONFORMANCE (golden, hand-authored): 160/160
ok`) and the recorded independent-rater agreement (`independent-rater
agreement (recorded live jev-1.13-free vs golden labels,
2026-10-02): 10/24 = 41.7%`). Neither gates the other. The final
status line names both failure counts, for example:
`PASS: golden 0 failures, bulk 0 failures`. Exit code 1 means a golden
or bulk case failed (the conformance number is golden), 2 means the
split, provenance, golden, or contamination checks failed closed,
3 means the Jev free window rate-limited and the run halted.

The report prints the case-file hash, the golden-file hash, the
provenance of both sets, and its own measured numbers on every run.

## Judge wiring

The judge protocol is Jev-shaped: typed calls (noul / choice / score)
that each return a verdict plus a confidence value. The offline stubs
(RuleJudge, FakeJudge, StrictRelationJudge, LenientRelationJudge) are
for unit tests and the offline eval only and are never labeled as Jev.

Offline relation judging is heterogeneous by construction. Every
offline `decide()` call in the eval and the tests runs through
`offline_relation_pair()`: StrictRelationJudge (conservative) paired
with LenientRelationJudge (permissive, marker-driven). The strict
judge reads a marker as being about the same slot only with at least
`RELATION_SHARED_TOKENS_MIN` (2) shared content tokens beyond
stopwords and numbers: one shared token, a shared number, a
near-homonym subject, or an address/number near-miss reads as
unrelated, so the pair vetoes and both facts stay live. The two
heuristics genuinely disagree on crafted near-misses (pinned in
`tests/test_judge_pairs.py` and `tests/test_relation_boundary.py`), so
a destructive act only proceeds when two distinct readings agree. Two
copies of one stub used to agree by construction, and that theater is
gone: a test shows the copied pair would tombstone a case the
heterogeneous pair vetoes.

When the strict minimum rose to two tokens, five golden cases whose
texts shared a single content token were reworded so the shared slot
is unambiguous (labels unchanged, same claims), and two single-token
near-miss cases that must KEEP were added. A test pins that every
destructive or marking golden claim meets the strict minimum.

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

The branch order in `Gate.decide` (confidence, play, sensitive, stop,
durable plus importance, else drop) is documented policy, not an
accident: confidence fails closed before any content branch is read,
play disposes of high-precision junk first, sensitive takes the one
disposition that retains nothing, stop is the strongest deny among the
remaining branches, and the only admitting branch runs last so every
deny gets the first chance. The rationale is stated in `gate.py` and
`thresholds.py`, and `tests/test_gate_precedence.py` pins the exact
action and reason string for every pair of branches firing at once,
the headline multi-signal inputs, and the boundary comparisons.

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
script skips cleanly with no network calls. On full completion with
the key present it refreshes `tests/fixtures/live_votes_20261002.json`
with the recorded live votes; the offline ratchet test
(`tests/test_live_ratchet.py`) reads that fixture and fails when
stub-vs-live agreement on the fixed 20-case sample drops below 0.40
(the recorded importance-audit 0.417 truncated down to the n=20 grid:
with 20 cases the floor moves in 0.05 steps, so 0.40 = 8/20 is the
tightest on-grid value at or below the measurement), so live drift is
a failing test instead of a footnote. On HTTP 429 it halts
honestly with the rate-limit message, never falls back to another
model, and never lets a stub answer in Jev's place. Pass
`--no-record` for dry runs with non-live judges so fake votes never
overwrite the recording.

## Lifecycle and store honesty

`human_override` documents and tests every action:

- `restore` clears the tombstone fields on the fact and clears
  conflict marks on both sides (own `conflict_with`, the counterpart
  fact mark where it still points back, and any `conflicts`-table
  rows naming the fact); it goes live again fully clean.
- `retire` soft-tombstones the fact toward `--target-id` (required),
  records the reason, and stores the actor as `human`.
- `tombstone` is the explicit alias of `retire`: the same soft
  tombstone toward `--target-id` (required), with the default reason
  `human-tombstone`.

All three are reachable from the CLI and documented in its help:

    unclutter override --db memory.db --fact-id 3 --action restore
    unclutter override --db memory.db --fact-id 3 --action retire \
        --target-id 5 --reason "user said so"
    unclutter override --db memory.db --fact-id 3 --action tombstone \
        --target-id 5

`Store.restore` is covered by tests including override-then-read-back,
restore-of-tombstone, and restore-of-conflict (both sides read fully
clean, conflicts rows removed). `Store.put` dedupes in two stages:
exact normalized content hash first (unchanged), then token-set
Jaccard at `DEDUP_JACCARD` (0.85) over live rows in the same user
scope, so same-fact near-duplicates (reordered words, a dropped word
in a long fact) merge while near-miss distinct facts stay separate.
Tokens are case- and punctuation-sensitive, matching the contract that
case and punctuation are content; resurrection stays exact-only (a
fuzzy match against tombstoned text inserts a fresh row); the
threshold is a `put` parameter tests can override. Limits, stated
plainly: a single-word change in a short fact still reads DISTINCT,
and heavily reworded paraphrases with little token overlap stay
DISTINCT. This stage catches near-duplicates, not deep semantic
equivalence. A repeat put of tombstoned text resurrects the
row as live with fresh source/created provenance (new put is new
life), pinned by put-after-tombstone tests; `Store.supersede` routes
its same-text path through `put` so it cannot silently return a dead
id. Supersede is scope-explicit: the caller user threads every path,
a caller scope that differs from the row owner raises ValueError
with nothing written, a missing id with an explicit user stores in
that caller scope, and a missing id without a user raises KeyError
instead of landing a row in the default scope. The exact-text fallback branch in `Store.put`
was dead code (a row whose text matches also carries the hash of that
text) and was removed; exact dedupe is by normalized content
hash, with the token-set near-duplicate stage above it, both pinned
by tests.

## Honesty

No benchmark numbers are claimed for the bulk labels: they are
rule-generated (provenance `synthetic-rule`), not human labels, and
this README quotes none of the eval numbers. The golden number is
contract conformance (stub-vs-frozen-human-reading: how often the
offline stub's reading matches the frozen human reading of the gate
contract), NOT accuracy and NOT memory quality, printed with both file
hashes on every run beside the recorded independent-rater agreement
(10/24 = 41.7%). The strongest independence bound (the pair/triple
conjunction search) is exceeded on the current labels and flagged for
human review; the independence claim is scoped to the resolutions
where the bound holds (see the eval section). Cost is marked ESTIMATE /
NOT VERIFIED, and contamination
checks run before anything is scored (train/test disjointness by case
hash and normalized text, golden disjoint from bulk, artifacts fail
closed).

## Known limit: paraphrase coverage on the read path

The offline recall and rerank path matches on surface text signals
(token overlap plus the documented stub features), not on deep semantic
equivalence. A heavily reworded query can therefore miss a stored fact:
recall returns fewer results or an empty list, and a supersede or
conflict vote over a paraphrased pair vetoes to KEEP with both facts
staying live. That miss is loud by design. An empty recall list is
visible to the caller, a vetoed pair leaves both rows live and
inspectable, and low-confidence gate input lands in the quarantine table
instead of being stored or dropped silently. Nothing on this path raises
on unseen input. `tests/test_recall_robust.py` pins it: 20 novel
paraphrases, disjoint from both eval sets, run through the offline read
path and must return without raising and with sane output shape (a list
of stored texts within cap, a pack string within budget). Raising
paraphrase catch rate without breaking frozen golden labels is future
work, tracked as a residual in `docs/master-plan.md`.

## Server and MCP transport (P3, built)

`src/uncluttered_memory/server.py` is a stdlib-only HTTP server over
the real Store/Gate: `POST /admit`, `POST /recall`, `POST /inject`,
`GET /status`, every call requiring a `user` it is scoped to.
Per-minute call and char budgets refuse with HTTP 429 plus one
structured log line (defaults in `thresholds.py`); env
`UNCLUTTER_KILL_SWITCH=1` or a kill file refuses every endpoint with
HTTP 503. When the judge halts (the JevError family, including 429),
the admit path quarantines and answers 429 with `quarantined: true`;
a gate-decided quarantine answers 200. There is no fallback model on
this path. `mcp/tools.json` defines the admit/recall/inject/review
tools and `mcp/adapter.py` serves them over stdio. Serve it with:

    unclutter serve --db memory.db --port 8765   # offline RuleJudge

## Not built yet: gauntlet recorder

`unclutter gauntlet` (recorded demo, P7) is a stub, not a feature. It
prints `not built until its phase` and exits 2, pinned by
`tests/test_cli.py`. There is no gauntlet recorder in this repo.
Server and MCP transport was a later phase per
`research/track-S3-server.md` and `docs/master-plan.md`, and it has
now landed as P3 above; nothing else in this README claims otherwise.
