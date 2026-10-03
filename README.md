# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

Every write is judged before it is stored. Every destructive act needs
committee agreement. Every number in this file is stated with its scope.

## Quickstart

    pip install -e .
    python3 -m pytest tests/          # offline suite, no key needed
    unclutter run                     # frozen eval: conformance + self-consistency
    python3 playground/demo.py        # six-line offline tour of every verdict
    unclutter serve --db memory.db --port 8765   # HTTP over the real store

The live Jev check runs only when `HERMES_CUSTOM_OPENCODE_AI_API_KEY`
is set; everything else is offline.

## Architecture overview

The write path and the read path are separate.

Write path:

    text -> Gate.decide (door guard + importance grader)
      -> STORE / QUARANTINE / DROP
      -> Store.put (free math dedupe)
      -> autospot bridge (suspicion screen + committee)
      -> live row, tombstone, conflict mark, or quarantine row

Read path:

    query -> Recall.select (rank, gate, band, cap at most 8)
      -> Injector.pack (whole cards, hard char budget)

Serving:

    Store + Gate behind server.py (HTTP) or mcp/adapter.py (stdio).

All decision cutoffs live in `src/uncluttered_memory/thresholds.py`.
`Gate.decide` and `Recall.select` take every cutoff as a parameter
defaulting to that file, so tests and calibration override values
without editing logic. Reason strings echo the effective value (for
example `stop>=0.58`), so an override is visible in the record. A test
pins that no other logic module hardcodes a numeric decision boundary.

## 1. Door guard: Gate.decide

File: `src/uncluttered_memory/gate.py`.

The judge answers one batch of typed questions per line (durable,
importance, stop, play, sensitive, plus confidence). Code owns every
decision after that. Unseen or low confidence input fails closed to
quarantine, never an exception.

Branch order is fixed policy, first match wins:

1. `conf < MIN_CONF (0.6)` -> QUARANTINE. Abstention. A judge that
   cannot answer never reaches a content branch.
2. `play > 0.7` -> DROP. High precision junk (word boundary laugh
   tokens, whole line identity claims) is disposed of first.
3. `sensitive > 0.7` -> DROP. Privacy outranks review. A private line
   must not be stored and must not sit in quarantine either, so it
   takes the one disposition that retains nothing. This is why it
   outranks stop: quarantine would still retain the text.
4. `stop >= 0.58` -> QUARANTINE. The strongest deny among the
   remaining branches. An over held line waits for review; a wrongly
   admitted line is already stored.
5. `durable >= 0.58 and importance >= 3` -> STORE. The only admitting
   branch, so it runs last. Every deny gets the first chance.
6. Anything else -> DROP (not durable or trivial).

`tests/test_gate_precedence.py` pins the exact action and reason string
for every pair of branches firing at once, plus headline multi signal
inputs and boundary comparisons.

RuleJudge is the offline heuristic stub used by tests and the offline
eval. It is not Jev and is never labeled as Jev. Its vote levels live in
`thresholds.py` (for example `FILLER_LEVELS`, `PLAY_SIGNAL`,
`DURABLE_DURABLE`); the cutoffs that read those votes are the gate
values above.

## 2. Importance grader: 1 to 5

The importance vote is an integer from 1 to 5 on every gate decision.
The store threshold is `IMPORTANCE_MIN = 3`: a durable line with
importance 1 or 2 drops as trivial.

The offline rubric earns 4 and 5 from compositional signals documented
in `gate.py`, not from marker word lists. The golden importance suite
was rewritten from human judgment of what is actually worth
remembering, deliberately breaking the old marker buckets: vital facts
with no marker words, trivial facts carrying marker words, and near
boundary judgments.

Four checks pin this in `tests/test_importance_independence.py`:
labels live in the data file (stripping every marker token leaves
stored labels unchanged while a stub mimicking marker predictor misses
widely); a coarse marker only classifier trained on half the suite
cannot reproduce held out labels (accuracy under 0.7); the same holds
at full resolution with a mirror image classifier that extracts the
full stub feature set under the same 0.7 bound; and the offline scorer
earns at least 3 marker free vitals and at least 3 marker bearing
trivials.

A fifth check, the strongest one, is EXCEEDED on the current labels
and flagged for human review (`eval/GOLDEN_CHANGELOG.md`). An
exhaustive conjunction search over all feature pairs (231) and triples
(1540) of the full 22 signal set, trained on even rows and scored on
held out odd rows, reaches 9/12 = 0.75 (best pair) and 10/12 = 0.833
(best triple), both above the 0.7 bound and above the fixed seed label
permutation null. Root cause is stated plainly: the direction of fit is
fixed (the stub is changed to meet the frozen labels) and the stub
reproduces every importance label exactly, so the labels are a function
of the tuned scorer signals by construction. This does not show the
labels were derived from the stub at authoring time and does not show
the labels are wrong; it means the independence claim is NOT made at
pair or triple resolution. The two checks are strict xfails: they fail
today and flip to failures if a changelogged review ever makes the
bound hold, so nothing resolves silently.

## 3. Free math: exact hash plus Jaccard 0.85

File: `src/uncluttered_memory/store.py`, threshold `DEDUP_JACCARD`.

`Store.put` dedupes in two stages, both free (no judge call), over live
rows in the same user scope:

1. Exact normalized content hash. Same text merges first.
2. Token set Jaccard at or above 0.85. Tokens are whitespace splits of
   the normalized text, case and punctuation sensitive, matching the
   contract that case and punctuation are content.

What 0.85 catches and what it does not: token reorderings score 1.0 and
merge; a dropped or added word merges once the fact is long enough
(7 tokens: 6/7 = 0.857). A single word change in a short fact stays
DISTINCT (`ship today the build` vs `ship the build` scores 3/4 =
0.75). Heavily reworded paraphrases with little token overlap stay
DISTINCT. The boundary is pinned: a pair scoring exactly 0.85 merges
(at or above), a pair just under it stays separate. Resurrection stays
exact only (a fuzzy match against tombstoned text inserts a fresh row).
The dead exact text fallback branch was removed; exact dedupe is by
normalized content hash. This stage catches near duplicates, not deep
semantic equivalence.

## 4. Four voter committee: 2 Jev votes plus Strict plus Lenient

Files: `src/uncluttered_memory/jev_client.py`,
`src/uncluttered_memory/supersede.py`.

Relation votes are one of: supersede, coexist, conflict_unresolved,
unrelated (plus the internal same marker for identical text). Only an
agreed supersede soft tombstones the old fact; an agreed clash marks
both facts conflict_unresolved and keeps both live, never a tombstone.

Offline pair: `offline_relation_pair()` returns StrictRelationJudge
(conservative) plus LenientRelationJudge (permissive). Strict requires
at least `RELATION_SHARED_TOKENS_MIN` (2) shared content tokens beyond
stopwords and numbers before it reads a marker as being about the same
slot. One shared token, a shared number, a near homonym subject, or an
address or number near miss reads as unrelated, so the pair vetoes and
both facts stay live. Lenient reads any update wording as a supersede
claim and any negation as a clash without checking the slot. The two
heuristics genuinely disagree on crafted near misses (pinned in
`tests/test_judge_pairs.py` and `tests/test_relation_boundary.py`), so a
destructive act only proceeds when two distinct readings agree. Two
copies of one stub used to agree by construction; a test shows the
copied pair would tombstone a case the heterogeneous pair vetoes.

When the strict minimum rose to two tokens, five golden cases whose
texts shared a single content token were reworded so the shared slot is
unambiguous (labels unchanged, same claims), and two single token near
miss cases that must KEEP were added. A test pins that every
destructive or marking golden claim meets the strict minimum.

Live path: `live_confirmed_decide()` takes two live Jev judges plus the
offline pair, four voters total. The two live judges must ask
differently worded questions (distinct instructions and criteria
framing; passing one identical question twice raises ValueError). A
TOMBSTONE or CONFLICT proceeds only when the live pair agrees with each
other AND the offline pair agrees with each other AND both agreed
relations match. Any disagreement vetoes to KEEP. `JevJudgeClient`
talks native Jev at `https://opencode.ai/zen/v1/systemone` with one
model, `jev-1.13-free`, set via `UNCLUTTER_JEV_MODEL`. The API key comes
from `HERMES_CUSTOM_OPENCODE_AI_API_KEY`; the session header is
`hermes-go-static-7f3a9c2e`.

There is no fallback model anywhere. On HTTP 429 the client raises
`RateLimited` and callers halt with a plain message. Pending items land
in the quarantine table, never voted by a stub, never redirected to
another model. Response parsing is pinned by recorded native fixtures
under `tests/fixtures/` replayed offline through the real parser.

## 5. Auto activation bridge: autospot.py

File: `src/uncluttered_memory/autospot.py`, wired through `Store.put`.

Every fresh `Store.put` insert runs the bridge (on by default). The
eval harness uses raw inserts (`auto_spot=False`) so the
contradict and supersede suites keep measuring committee votes in
isolation.

Two stages:

1. Free suspicion screen. Token overlap at `AUTOSPOT_MIN_JACCARD` =
   0.30 plus one change signal: a change marker in the new text, a
   differing content detail, or a changed number detail such as a moved
   time. Same user live rows only. The screen nominates, never decides.
   It sits well below the 0.85 dedupe line so reworded same slot
   updates are caught; the weakest genuine same slot update in the
   frozen fixtures scores 0.40. Deep paraphrases with little token
   overlap stay below it by construction, same as dedupe.
2. Committee verdict. Offline Strict plus Lenient pair by default (no
   network); the live dual Jev path where the operator wired a live
   pair (live plus offline agreement required for any destructive act).
   An agreed supersede tombstones with reason `supersede-auto-spot`;
   an agreed clash conflict marks with reason
   `conflict_unresolved-auto-spot`; both write actor `auto-spot`, so
   auto rows read apart from manual (`code`) and human rows. Vetoes and
   KEEP write nothing.

Caps and toggles:

- At most `AUTOSPOT_MAX_PAIRS_PER_WRITE` (5) flagged pairs reach the
  committee per write, strongest suspicion first. The live path asks two
  differently worded Jev questions per pair, so the worst case is twice
  that many live calls per write, inside the per minute server budget.
- The live path shares the server rate limiter (offline votes spend no
  budget; an exhausted budget stops the run; a halted judge keeps both
  facts live and reports it).
- Opt out at three levels: `Store(auto_spot=False)` for a store,
  `put(auto_spot=False)` for one call, `unclutter serve --no-auto-spot`
  for the server (raw inserts instead of screened ones).

Failure mode, argued as accepted risk: the offline default lets two
heuristics tombstone a live fact with no human in the loop, at the same
heterogeneous agreement bar as the manual committee (any disagreement
vetoes to KEEP). A wrong but agreed verdict costs one soft, restorable
row with auto spot provenance pointing at the cause. `auto_spot=False`
keeps a human in the loop.

## 6. Store: tombstones, provenance, per user cap

File: `src/uncluttered_memory/store.py`.

SQLite with per user scoping on every row. Tables: facts, quarantine,
conflicts (unresolved pairs), plus tombstone fields on the facts row
instead of deletes.

- Soft tombstones, never rewrites. `supersede` never inserts on a
  missing id: an unknown id raises `OrphanSupersedeError` (a `KeyError`)
  and writes nothing anywhere, so a typo cannot read as success.
  Supersede is scope explicit: a caller scope that differs from the row
  owner raises ValueError with nothing written. A repeat put of
  tombstoned text resurrects the row as live with fresh
  source and created provenance (new put is new life).
- Human override (`unclutter override --help`, three actions):
  `restore` clears tombstone fields and clears conflict marks on both
  sides (own `conflict_with`, the counterpart mark, and any
  `conflicts` table rows naming the fact); `retire` soft tombstones
  toward `--target-id` (required) with actor `human`; `tombstone` is
  the explicit alias of `retire` with default reason
  `human-tombstone`.
- Row provenance, exactly as stored: `gate_action` (the gate verdict,
  `STORE` on judged rows), `importance` (the voted 1 to 5), `judge`
  (the judge identity: live model name such as `jev-1.13-free`, or
  `stub:RuleJudge` / `stub:FakeJudge` offline), `decided_at` (unix time
  of the decision). `Store.admit` fills all four from the gate decision
  on STORE. `put` and `supersede` take them as keywords and write them
  on inserts, resurrections, and merges (a plain re put refreshes only
  provided fields, never NULLs over judged provenance). A ghostwriter
  direct SQL insert leaves all four NULL, so `get()` and `live()` both
  tell a judged row from an unjudged one at read time. Operator bypass
  rows (`release`, `approve_quarantine`) go through `put` with no gate
  vote and read NULL like direct inserts: only `admit` rows claim a
  judge. Databases created before these columns migrate on open.
- Per user memory cap: `PER_USER_MEMORY_CAP` (10000),
  constructor parametrized (`None` means unbounded). Counts live rows
  in one user scope. A fresh insert into a full scope is refused loudly:
  `put` raises `MemoryCapExceeded`; `admit` holds the item in
  quarantine with reason `per-user-memory-cap`. Merges and exact text
  hits add no row and never trip the cap. Never counted as a coding bug.
- Error honesty: `Store.admit` quarantines only judge halt exceptions
  (the JevError family: rate limit, bad key, transport, malformed judge
  answer). Any other exception is a coding bug that increments an
  explicit `error_count`, emits one structured log line (time, op,
  input hash, error type), and propagates instead of vanishing as a
  quarantine.

## 7. Recall and inject: rank, pack at most 8

Files: `src/uncluttered_memory/recall.py`,
`src/uncluttered_memory/inject.py`.

`Recall.select` takes scored `(text, score)` pairs and returns at most
`RECALL_CAP` (8) texts. Steps: keep scores at or above `RECALL_GATE`
(0.58); if none, return empty; set floor at best score times
`(1 - RECALL_BAND)` with `RECALL_BAND` (0.45); keep scores at or above
the floor; sort best first; cut at cap. Gate, band, and cap are
parameters defaulting to `thresholds.py`. Per task calibration can
lower the gate, which is when the band does its cutting (at the default
gate the gate dominates, by design).

Packing is whole card only with a hard char budget used as a cheap
proxy for model tokens (about 4 chars per token, so 4000 chars is
roughly 1000 tokens; chars are exact and dependency free while real
tokenizers differ per model). `Recall.pack` and `Injector.pack` never
emit a partial card; the cut lands on a card boundary. `Injector.pack`
sorts cards best first, packs exact duplicate card texts once (first,
best scored occurrence wins), and stops before exceeding
`INJECT_BUDGET_CHARS` (4000). Limits, stated plainly: recall matches
surface wording, not deep paraphrase; a heavily reworded query can miss
a stored fact and return fewer results or an empty list. That miss is
loud by design (visible empty list, vetoed pairs stay live and
inspectable, low confidence input quarantines instead of storing
silently). `tests/test_recall_robust.py` pins 20 novel paraphrases,
disjoint from both eval sets, that must return without raising and with
sane output shape.

## 8. Server and MCP transport

Files: `src/uncluttered_memory/server.py`, `mcp/tools.json`,
`mcp/adapter.py`.

`server.py` is a stdlib only HTTP server over the real Store and Gate:

- `POST /admit` `{user, text, source}`: STORE, DROP, or QUARANTINE.
- `POST /recall` `{user, query}`: scored live rows for that user,
  packed.
- `POST /inject` `{user, query}` or `{user, cards}`: packed context
  string within budget.
- `GET /status` (or `POST /status`): scoped counts.
- Every call requires a `user` it is scoped to.

Guards: per minute call and char budgets refuse with HTTP 429 plus one
structured log line (defaults `RATE_LIMIT_CALLS_PER_MIN` 120 and
`RATE_LIMIT_CHARS_PER_MIN` 200000 in `thresholds.py`); env
`UNCLUTTER_KILL_SWITCH=1` or a kill file refuses every endpoint with
HTTP 503. When the judge halts (the JevError family, including 429),
admit quarantines and answers 429 with `quarantined: true`; a gate
decided quarantine answers 200. No fallback model on this path.

MCP: `mcp/tools.json` defines the admit, recall, inject, and review
tools; `mcp/adapter.py` serves them over stdio (`tools/list`,
`tools/call`), sharing the `MemoryApp` handlers with the server. Every
tool requires a user.

Serve it with:

    unclutter serve --db memory.db --port 8765   # offline RuleJudge

Add `--no-auto-spot` to serve raw inserts (bridge off).

## 9. Honesty: what the numbers are

- **Contract conformance (golden, hand authored): 160/160.** How often
  the offline stub reading matches the frozen human reading of the gate
  contract. NOT accuracy, NOT memory quality. Census: admit 56,
  importance 24, dedupe 20, contradict 23, supersede 23, rerank 14,
  pinned exactly by `tests/test_golden.py`. Labels frozen at the
  2026-10-02 freeze (`eval/golden_labels_frozen.json`,
  `eval/GOLDEN_CHANGELOG.md`): the stub is changed to meet them; a
  label changes only for documented human error with a changelog entry,
  never to satisfy the scorer. Undocumented edits fail the suite
  (`tests/test_golden_freeze.py`).
- **Paid rubric (`jev-1.13`, live): importance 20/24 = 83.3%, admit
  40/56 = 71.4%.** Live vs label on the golden set with the rubric
  prompt (see `docs/calibration-20261002-114232-rubric.md`). Paid key
  runs only; never a repo default.
- **Free tier (`jev-1.13-free`, live): 10/24 = 41.7%.** Independent
  rater agreement with the golden labels; varies run to run (see
  `docs/label-audit-20261002.md`). Information only; it gates nothing.
- **Paraphrase battery: 92/92 = 100%.** Two hand written paraphrase
  pairs per golden contradict and supersede case, measuring how often
  the offline pair reaches the same disposition as the frozen label.
  Floor pinned at 90% so a regression fails the suite. Two boundary
  rewrites the pair is documented NOT to catch (a deep tombstone
  rewrite that drops the strong update marker, and a marker free
  conflict rewrite) are pinned in the same file
  (`tests/test_paraphrase_battery.py`); rewrites that drop the marker
  family or fall below two shared content tokens are documented misses.
- **Suite size: 438 tests.** Collected offline with no key. The report
  prints two numbers on every run, golden first: contract conformance
  (`CONTRACT CONFORMANCE (golden, hand-authored): 160/160 ok`) and the
  recorded independent rater agreement (`independent-rater agreement
  (recorded live jev-1.13-free vs golden labels, 2026-10-02): 10/24 =
  41.7%`). Neither gates the other. Exit codes: 1 means a golden or
  bulk case failed, 2 means the split, provenance, golden, or
  contamination checks failed closed, 3 means the Jev free window rate
  limited and the run halted. The report prints the case file hash, the
  golden file hash, the provenance of both sets, and its own measured
  numbers on every run.

Limits, stated plainly with the numbers: the strongest
importance independence bound (feature pairs and triples) is exceeded
on the current labels and flagged for human review; cost figures are
ESTIMATE and NOT VERIFIED; no benchmark numbers are claimed for the
synthetic bulk set (self consistency only); contamination checks
(train and test disjointness by case hash and normalized text, golden
disjoint from bulk, artifacts fail closed) run before anything is
scored, and every contamination flag carries a machine readable reason.

## 10. Eval, calibration, console

- `eval/run.py`: one command eval over two case sets (hand authored
  golden for the claim, synthetic bulk for self consistency). Per suite
  tables, admit precision, recall, F1, latency, cost per 1k estimate,
  contamination scans that fail closed. `eval/golden.jsonl`
  (provenance `hand-authored`) shares no code path with the stubs and
  no text with the bulk set (a test proves it); `eval/cases.py`
  generates the bulk `eval/frozen.jsonl` only (provenance
  `synthetic-rule`).
- `src/uncluttered_memory/calibrate.py`: per task threshold registry
  fingerprinted to the task name, refuses mismatched files,
  UNCALIBRATED default, train only tuning. CLI `calibrate` and
  `conformal` commands default output to the operator current working
  directory, outside the repo scan tree; pointing `--out` inside
  `thresholds/` or `eval/thresholds*` prints a loud warning, because
  the next `unclutter run` scans that tree and fails closed on a bad
  file there (`tests/test_calibration_footgun.py`).
- Console: `eval/run.py` and the CLI call `configure_console()`, which
  reconfigures stdout and stderr to UTF-8 with
  `errors="backslashreplace"`. A cp1252 console cannot mangle the
  report; unencodable characters degrade to visible escapes. The
  success line is pinned byte for byte by `tests/test_encoding.py`.
- Live spotcheck (`scripts/live_spotcheck.py`, information only):
  samples 20 golden cases deterministically against live
  `jev-1.13-free` and prints stub vs live agreement. Gates nothing. On
  full completion with the key present it refreshes
  `tests/fixtures/live_votes_20261002.json`; the offline ratchet test
  (`tests/test_live_ratchet.py`) fails when stub vs live agreement on
  the fixed 20 case sample drops below 0.40. Pass `--no-record` for dry
  runs so fake votes never overwrite the recording.

## 11. File map

- `src/uncluttered_memory/gate.py`: door guard plus 1 to 5 grader.
- `src/uncluttered_memory/thresholds.py`: every cutoff default.
- `src/uncluttered_memory/store.py`: SQLite, dedupe math, tombstones,
  provenance, per user cap.
- `src/uncluttered_memory/supersede.py`: code ordered candidate pairs,
  committee verdict application.
- `src/uncluttered_memory/jev_client.py`: native Jev client plus
  Strict and Lenient offline relation judges.
- `src/uncluttered_memory/autospot.py`: auto activation bridge.
- `src/uncluttered_memory/recall.py`: rank, gate, band, cap at most 8.
- `src/uncluttered_memory/inject.py`: card first packing.
- `src/uncluttered_memory/server.py`: HTTP over the real store.
- `src/uncluttered_memory/cli.py`: `run`, `serve` (with
  `--no-auto-spot`), `override`, `calibrate`, `conformal`.
- `src/uncluttered_memory/calibrate.py`: per task registry.
- `src/uncluttered_memory/console.py`: UTF-8 forced streams.
- `mcp/tools.json`, `mcp/adapter.py`: MCP stdio transport.
- `eval/run.py`, `eval/golden.jsonl`,
  `eval/golden_labels_frozen.json`, `eval/GOLDEN_CHANGELOG.md`,
  `eval/cases.py`: frozen eval.
- `scripts/live_spotcheck.py`: information only live sample.

## 12. Not built yet: gauntlet recorder

`unclutter gauntlet` (recorded demo, P7) is a stub, not a feature. It
prints `not built until its phase` and exits 2, pinned by
`tests/test_cli.py`. There is no gauntlet recorder in this repo.
