# Track B: Honcho OSS Deep Dive

Source commit: `9d6fe8c` (2026-09-29). Clone at `/root/.hermes/cache/scratch/honcho`.
Hermes docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho

## 1. Exact write path

### 1.1 Store: messages land on a session, then enqueue to background queue
- The Honcho Loop is Store, Reason, Query, Inject. Workspaces hold peers, peers join sessions, messages live on sessions, and Honcho builds a per-peer representation queried via Chat endpoint or directly. (`README.md:66-73`)
- `POST /messages` persists message rows then fires `background_tasks.add_task(enqueue, payloads)` so the HTTP response does not wait for reasoning. (`src/routers/messages.py:161`, `src/routers/messages.py:246`)
- `enqueue()` first cancels pending dreams for the sending peer (user active again), then `handle_session()` resolves config and inserts one `QueueItem` row per task into Postgres. (`src/deriver/enqueue.py:33-76`)

### 1.2 Fanout: one message becomes representation and/or summary queue items
- `generate_queue_records()` runs per message. Summary items are created only when `seq_in_session % messages_per_short_summary == 0` or `% messages_per_long_summary == 0`. (`src/deriver/enqueue.py:293-341`)
- Representation items are created only if `reasoning.enabled` and the sender passes the observe gate. Observers list = self (sender observes self) plus every other active session peer whose `observe_others` is true. One queue record carries all observers. (`src/deriver/enqueue.py:344-388`)
- Observe gate precedence: session-level `observe_me` wins if set, else peer-level `observe_me`, else default true. A peer that left the session is skipped as observer. (`src/deriver/enqueue.py:257-291`)
- Hermes exposes the same knobs: `observationMode` directional (all on) or unified (shared pool), plus per-peer `observeMe`/`observeOthers` overrides; server-side dashboard toggles win over local defaults. (Hermes docs URL above, observation section)

### 1.3 Batching gate: deriver claims work only past token or age threshold
- Representation work units accumulate until summed unprocessed-message tokens reach `REPRESENTATION_BATCH_WORK_UNIT_TARGET_TOKENS` (default 512), or oldest item age passes `REPRESENTATION_BATCH_MAX_AGE_SECONDS` (default 1800s), or `FLUSH_ENABLED` bypasses. (`src/config.py:949-973`, `src/crud/deriver.py:18-44`)
- Single deriver LLM call drains a claimed unit with a conversation window capped at `REPRESENTATION_BATCH_TARGET_INPUT_TOKENS` (default 1024, first message always included). Hard input cap `DERIVER.MAX_INPUT_TOKENS` = 25000. (`src/config.py:938-965`)
- Deriver worker polls every `POLLING_SLEEP_INTERVAL_SECONDS` (1s) with backoff to 30s when idle. (`src/config.py:883-909`)

### 1.4 Deriver LLM call: one structured-output call, explicit facts only
- `process_representation_tasks_batch()` builds one prompt from batched messages and makes a single `honcho_llm_call` with `response_model=PromptRepresentation`, `json_mode=True`, retry 3x, model default `openai/gpt-5.4-mini`. (`src/deriver/deriver.py:43-56`, `src/deriver/deriver.py:139-188`)
- Prompt extracts explicit atomic facts about the target peer only: `target="true"` messages are the source, `target="false"` messages are context only and must never yield facts. Empty target batches should yield few or zero conclusions. (`src/deriver/prompts.py:62-118`)
- Deductive observations exist in the schema (`deductive` vs `explicit` levels) but the current minimal deriver prompt only extracts explicit facts; deductive synthesis now lives in the dreamer/dialectic path, not this call. (`src/deriver/deriver.py:210-230`, `src/crud/representation.py:199-232`)

### 1.5 Save: embed, dedup, store as documents in per-pair collections
- `RepresentationManager.save_representation()` drops empty observations, batch-embeds all texts via `embedding_client.simple_batch_embed` (oversize truncated), then bulk-creates documents. (`src/crud/representation.py:74-176`)
- Storage is one collection per (workspace, observer, observed) pair; each conclusion is a document with content, session name, level (explicit/deductive), message-id provenance, premises metadata. (`src/crud/representation.py:177-232`)
- Dedup is on by default (`DERIVER.DEDUPLICATE=true`): exact plus semantic duplicate detection with reject/replace counts reported in telemetry. (`src/config.py:933-934`, `src/deriver/deriver.py:226-256`)
- After save, dream scheduling is checked per collection if `dream.enabled`. (`src/crud/representation.py:228-232`)

### 1.6 Summaries: deterministic cadence, separate queue task
- Short summary every 20 messages, long summary every 60 messages; caps 1000 and 4000 tokens respectively. (`src/config.py:1200-1227`)
- Summary queue items are processed by `process_item(task_type="summary")` via `src/utils/summarizer.py` (`create_short_summary`, `create_long_summary`, `summarize_if_needed`). (`src/deriver/consumer.py:92-120`, `src/utils/summarizer.py:201-339`)
- Summary model default is also `openai/gpt-5.4-mini`. (`src/config.py:1205-1213`)

### 1.7 Dialectic cadence (Hermes layer on top of Honcho server)
- Hermes polls two layers per turn: base `context()` refresh every `contextCadence` turns (default 1) and dialectic `peer.chat()` refresh every `dialecticCadence` turns (default 2, recommended 1-5). `dialecticDepth` (default 1, clamp 1-3) sets passes per dialectic invocation with early bailout on strong signal. (Hermes docs URL above, config table)
- Session-start prewarm fires one background dialectic call at full depth; turn 1 uses it if landed, else a bounded synchronous fallback. (Hermes docs URL above, prewarm section)
- Query-adaptive level: auto dialectic scales base `dialecticReasoningLevel` up 1 at 120+ chars, up 2 at 400+ chars, clamped at `reasoningLevelCap` (default high); `reasoningHeuristic:false` pins it. (Hermes docs URL above)

## 2. Exact read path

### 2.1 Session context endpoint: `GET /workspaces/{wid}/sessions/{sid}/context`
- Handler `get_session_context` with query params: `tokens`, `summary` (include flag), `search_query`, `peer_target`, `peer_perspective`, `scope`, `sessions` allowlist, `limit_to_session`, `search_top_k/max_distance`, `include_most_frequent`, `max_conclusions`. (`src/routers/sessions.py:705-787`)
- Without `peer_target`: returns summary plus recent messages only, no representation or card. (`src/routers/sessions.py:889-917`)
- With `peer_target`: observer = `peer_perspective or peer_target`; scope swaps observer to the scope peer; peer-scoped keys may only read their own perspective. (`src/routers/sessions.py:920-938`)

### 2.2 Two-layer injection (Hermes wording) maps to server assembly order
- Hermes docs call it two-layer: base layer (`session.context()` result: summary plus representation plus card plus recent messages) concatenated with dialectic layer (`peer.chat()` synthesized answer), truncated to `contextTokens` budget (default null, uncapped; example cap 1200; dialectic slice capped at `dialecticMaxChars` 600). (Hermes docs URL above, architecture and config table)
- Server-side assembly for peer-targeted context: (1) working representation via `crud.get_working_representation`, (2) peer card via `crud.get_peer_card` (dropped under any allowlist because cards carry no per-session provenance), (3) both short and long summaries fetched, (4) budget adjusted, (5) messages fill remainder. (`src/routers/sessions.py:964-1025`)

### 2.3 Budgets: 40/60 split, representation subtracted first
- Token ceiling: `tokens` param or `GET_CONTEXT_MAX_TOKENS` (default 100000, max 250000). (`src/routers/sessions.py:794-796`, `src/config.py:1517`)
- Representation plus card tokens are subtracted first: `adjusted_limit = token_limit - tokens(representation) - tokens(card)`. (`src/routers/sessions.py:1004-1007`)
- `_select_summary_for_context`: 40% of adjusted budget for summary; pick long if it fits and is longer than short, else short if it fits; if neither fits, summary is null and all budget goes to messages. (`src/routers/sessions.py:212-264`; docstring at `src/routers/sessions.py:788-793`)
- Working representation capped at `WORKING_REPRESENTATION_MAX_OBSERVATIONS` (default 100) with semantic top-k, max-distance, most-derived, and max-observations overrides from query params. (`src/routers/sessions.py:50-99`, `src/config.py:943-947`)

### 2.4 Dialectic recall (the `peer.chat()` side): agentic tool loop
- `DialecticAgent` prefetches session history (up to `SESSION_HISTORY_MAX_TOKENS`, default 4096) then runs a tool loop: full loadout 7 tools (search_memory, get_reasoning_chain, get_observation_context, search_messages, grep_messages, get_messages_by_date_range, search_messages_temporal), minimal level 2 tools (search_memory, search_messages). (`src/dialectic/core.py:59-151`, `scripts/dialectic_cost_calculator.py:26-35`, `src/config.py:1111-1115`)
- Reasoning levels: minimal (1 iter, 250 out tokens), low (5), medium (2), high (4), max (10); all default model `openai/gpt-5.4-mini`; workspace chat gets +3 extra iterations except at minimal. (`src/config.py:1051-1109`)
- Dialectic input cap 100000, output cap 8192, history tool cap 8192. (`src/config.py:1099-1103`)
- Cost targets per level: minimal $0.001, low $0.01, medium $0.05, high $0.10, max $0.50; first-iteration input ~= system 2000 + tools (~350 each) + peer cards 500 + session history + prefetch 2000 (800 minimal) + query 200. (`scripts/dialectic_cost_calculator.py:37-44`, `scripts/dialectic_cost_calculator.py:71-130`)
- Peer cards are injected into the system prompt and flagged as convenience summaries, not separate truth: card facts originate from the same observations `search_memory` can find. (`src/dialectic/prompts.py:178-200`)

## 3. Self-host cost

### 3.1 What you run
- Five services from compose: api (8000), deriver worker, mcp (3000), Postgres with pgvector (5432), Redis (6379); prebuilt image `ghcr.io/plastic-labs/honcho:latest` or build from source; `honcho start --setup` is the CLI path. (`docs/v3/contributing/self-hosting.mdx:64-115`)
- Server fails to start with no LLM provider. Built-in defaults: text generation `openai/gpt-5.4-mini`, embeddings `openai/text-embedding-3-small`; any OpenAI-compatible endpoint (OpenRouter, Together, Fireworks, Ollama, vLLM, LiteLLM) works but models must support tool calling. (`docs/v3/contributing/self-hosting.mdx:37-62`)

### 3.2 Bill of materials (recurring)
- Infra minimum: 1 small VM (2 vCPU/4GB is enough for API plus deriver plus local Postgres/Redis at hobby scale), plus managed Postgres with pgvector if not local (Supabase/Railway free tier exists per docs). (`docs/v3/contributing/self-hosting.mdx:29-35`)
- LLM spend (managed-service proxy for self-host token burn): deriver 1 call per claimed batch (batch ~1024 input tokens plus prompt scaffold) plus embedding per observation; summary 1 call per 20/60-message boundary (up to 1000/4000 out tokens); dialectic per Hermes cadence: base context call is embedding-only (cheap) but each `peer.chat()` is 1 tool-loop session at the configured level ($0.001 to $0.50 target). At Hermes defaults (context every turn, dialectic every 2 turns, depth 1, level low) a 100-turn session runs ~50 low-level dialectic calls, target ~$0.50 in LLM cost before output tokens. Arithmetic from `scripts/dialectic_cost_calculator.py:37-44` and Hermes defaults table; NOT VERIFIED against live billing.
- Managed alternative: api.honcho.dev with $100 free credits per new org. (`README.md:77`)
- Pricing table used by the cost calculator (Jan 2025 sellers): gemini-2.5-flash-lite $0.10/$0.40, gemini-3-flash-preview $0.50/$3.00, haiku-4-5 $1.00/$5.00, opus-4-5 $5.00/$25.00 per 1M in/out. (`scripts/dialectic_cost_calculator.py:46-68`)

## 4. Where LLM spend is wasted

1. Dialectic tool-loop over-iteration: default low allows 5 tool rounds plus session-history prefetch; many factual recall queries could stop after the prefetch plus 1 search. Extra rounds burn input (whole history resubmits each round) for no new evidence. (`src/config.py:1070-1074`, `src/dialectic/core.py:171-173`, `scripts/dialectic_cost_calculator.py:127-129`)
2. Prefetch-then-search duplication: 2000 tokens of prefetched observations plus 4096 session history load before the model searches anyway; the search often returns what prefetch already contained. (`scripts/dialectic_cost_calculator.py:32-35`, `src/config.py:1111-1115`)
3. Uncapped Hermes injection defaults: `contextTokens` null plus `contextCadence` 1 means full base context resubmits every turn even when nothing changed; `dialecticMaxChars` 600 truncates after generation, so generation tokens are already spent. (Hermes docs URL above, config table)
4. Deriver calls on low-signal batches: batches with zero `target=true` messages still cost a full LLM call that is instructed to emit few or zero conclusions; agent tool-output sessions are the worst case. (`src/deriver/prompts.py:90-92`, `src/deriver/deriver.py:217-224` logs zero-observation warnings)
5. Summary regeneration boundaries: short summary every 20 messages re-summarizes from scratch up to 1000 tokens; long tail sessions pay repeatedly for overlapping windows. (`src/config.py:1200-1227`, `src/utils/summarizer.py:201-280`)
6. Embedding every observation plus every search: each saved conclusion is embedded once, then each `search_query` context call embeds the query again; high `contextCadence` with `search_query` set multiplies embedding calls per turn. (`src/crud/representation.py:116-140`, `src/routers/sessions.py:940-951`)
7. Dream pipeline on top: dream scheduling per collection after each save plus dream LLM calls during idle; cancelled on new activity, so bursty sessions can schedule-then-cancel repeatedly. (`src/crud/representation.py:228-232`, `src/deriver/enqueue.py:43-60`)

## 5. Top 5 weaknesses a Jev layer could fix (mechanism each)

1. No calibrated confidence on conclusions. Everything downstream (40/60 budget, top-k, card synthesis) treats a guessed preference and a stated fact identically, so truncation drops high-certainty facts as readily as guesses. Jev fix: score each deriver conclusion at write time with a typed judgment (choice/score) plus calibrated probability; persist `p` alongside the document; rank representation candidates by expected value (relevance times p) instead of recency plus vector distance. Touches `RepresentationManager.save_representation` and `get_working_representation` ordering.
2. Recall-or-generate decision is unpriced. The dialectic always runs the LLM loop even when prefetch already contains the answer; there is no cheap gate. Jev fix: 70-500ms Jev triage call before the loop with alternatives [answer_from_prefetch, search_then_answer, full_loop]; skip the loop when P(answer_from_prefetch sufficient) exceeds threshold. Saves the $0.01 low-level call on the easy fraction.
3. Tool-choice and stop decisions are prompt hopes. `TOOL_CHOICE auto` plus max-iteration caps mean the model decides how many paid rounds to run with no budget awareness. Jev fix: per-round Jev choice (continue_search vs synthesize_now) with value-of-information scoring; hard stop when marginal expected gain is below the priced cost of another round. Replaces fixed caps (5/4/10) with adaptive stopping.
4. Batching gate is token-count only, quality blind. The 512-token/1800s gate claims low-signal batches (tool output, status pings) that yield zero conclusions after a paid call. Jev fix: pre-deriver Jev screen (worth_deriving vs skip) on batch features (target-message ratio, novelty vs existing collection centroid, novelty terms); skip or defer batches below threshold, spending the call only where expected conclusions per dollar clears bar.
5. Summary cadence is message-count only, stasis blind. Sessions that repeat the same topic for 60 messages pay for re-summarization that adds nothing; sessions that pivot sharply wait up to 20 messages for a refresh. Jev fix: Jev drift judgment per batch (topic_shift score 0-1); trigger summary early on shift, delay it on stasis. Same summary budget, fewer wasted calls and fresher context.

## 6. Gaps (NOT VERIFIED)

- Live per-call dollar figures: cost calculator gives targets and Jan 2025 price table, but actual spend per level against current `gpt-5.4-mini` pricing is NOT VERIFIED (no live billing run in this track).
- Managed Honcho price per 1k calls or per seat beyond the $100 credit is NOT VERIFIED (pricing page not read in this track).
- Peer card generation path (which LLM call synthesizes card lines from conclusions, and its cadence) is NOT VERIFIED (card CRUD read, synthesis caller not traced).
- Dreamer specialist prompts and dream LLM cost are NOT VERIFIED (files listed, prompts not read).
- Whether `deductive` level documents are still written by any current path (vs legacy schema) is NOT VERIFIED (minimal prompt is explicit-only; dreamer writeback not traced).
- Hermes plugin internals (exact truncation order inside `contextTokens`, prewarm timeout seconds) are NOT VERIFIED beyond what the docs page states (Hermes source not read in this track).
