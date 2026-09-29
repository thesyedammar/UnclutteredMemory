# Track C: OSS Memory Landscape

Survey date: 2026-09-29. Sources: official docs and GitHub READMEs via web extracts (7 ops total: 2 searches + 5 extracts). Star counts are approx and move daily.

## 1. Mem0 (mem0ai/mem0)

- Stars: approx 48k+ (secondary 2026 roundup figure; exact live count NOT VERIFIED, README page render did not expose it)
- What it stores: layered conversation memory. Four scopes: conversation (current turn), session (short task facts keyed by run_id), user (long term facts keyed by user_id), organizational (shared team context). Within layers: factual (preferences), episodic (interaction summaries), semantic (concept relations).
- How it retrieves: vector search over memories plus hybrid BM25 keyword and entity boosting. v3 (April 2026) uses single-pass retrieval at top_200 budget. Retrieval ranks user memories first, then session notes, then raw history.
- Where the LLM is called: write path (extract facts, decide ADD/UPDATE/DELETE; v3 leans to ADD-only single pass) and read path (query rewriting and answer-time injection). Default stack per README: gpt-5-mini for LLM, text-embedding-3-small for embeddings, both swappable.
- Pricing/self-host story: Apache 2.0. Three modes: pip/npm library for prototyping, self-hosted server via docker compose (auth on by default), Cloud platform at app.mem0.ai for zero-ops production. Managed platform has proprietary optimizations not in OSS SDK.
- Top weakness: LLM on both write and read means cost and latency scale with every turn, and flat fact promotion loses temporal structure (superseded facts are overwritten or accumulate rather than versioned with validity intervals).

## 2. Zep (getzep/zep, Graphiti engine)

- Stars: 4.9k (verified from GitHub page extract)
- What it stores: temporal Context Graph per user or subject. Nodes are entities, edges are facts/relationships with validity intervals (when a fact became true, when it became invalid). Six context primitives: facts, entities, episodes, thread summaries, observations, user summaries.
- How it retrieves: graph.search (low level) and thread.get_user_context (high level) assemble a token-efficient Context Block string from selected graph data. Governed Context Lake controls agent access.
- Where the LLM is called: ingest (entity/relation extraction from chat, business data, docs, JSON; fact invalidation decisions; summarization) and retrieval assembly. Debug mode on paid tiers captures LLM reasoning traces for ingestion steps.
- Pricing/self-host story: OSS repo exists (examples/integrations); docs reference Flex, Flex Plus, Enterprise tiers with governance, observations, debug traces. Exact current prices and self-host image status NOT VERIFIED.
- Top weakness: graph quality depends on LLM extraction on every ingest, so noisy input or rapid fact churn raises cost and risks wrong edges; heaviest option when all you need is simple user facts.

## 3. Letta, formerly MemGPT (letta-ai/letta)

- Stars: 24.7k (verified from GitHub page extract)
- What it stores: agent-managed state. Core memory in labeled editable blocks (canonical human block for user facts, persona block for agent identity), archival memory for overflow outside the context window, shared blocks for multi-agent state. Newer Agent SDK adds filesystem-style git-tracked memory on top of blocks.
- How it retrieves: the agent itself reads and rewrites blocks through tools, paging archival content into context when needed. New v1 agent supports Responses API, encrypted reasoning tokens, and sleep-time compute (background consolidation between sessions).
- Where the LLM is called: everywhere by design. The agent curates its own memory, so every keep/archive/rewrite decision is an LLM tool call.
- Pricing/self-host story: Apache 2.0. Self-host via App Server locally (letta server), desktop app, or Letta Cloud for cross-machine memory and identity. Exact cloud prices NOT VERIFIED.
- Top weakness: giving the agent authority over its own context is powerful but unguarded. Bloated or self-reinforcing blocks, no calibrated scoring of what deserves to stay, and debugging why the agent kept something is hard.

## 4. LangGraph memory + LangMem (langchain-ai/langgraph)

- Stars: 42.4k on langgraph repo (verified from GitHub page extract)
- What it stores: two tiers. Short-term: thread-scoped checkpoints (message history plus files, docs, artifacts in graph state). Long-term: cross-thread store with custom namespaces, typed as semantic memory, profile (user facts), collection (open sets), episodic (past episodes), procedural (behavior rules). LangMem adds functional primitives for extraction and prompt optimization.
- How it retrieves: developer-controlled. Checkpointer resumes thread state; BaseStore lookup by namespace at any point in any thread. No automatic injection; you choose what enters the prompt.
- Where the LLM is called: only where the developer puts it. LangMem extraction and prompt-optimization steps optionally use an LLM; hot-path writes and background consolidation are both supported patterns. Storage backends range from in-memory to AsyncPostgresStore.
- Pricing/self-host story: OSS (MIT-style LangChain licensing; exact file NOT VERIFIED here). Self-host any checkpointer/store backend. Paid LangSmith cloud for tracing, evals, managed deploys. Exact LangSmith prices NOT VERIFIED.
- Top weakness: least opinionated means most work. No built-in extraction quality, ranking, or judgment; every team re-implements curation and ends up with ad hoc prompts that drift.

## 5. OpenAI memory (ChatGPT memory + Responses/Agents APIs)

- Stars: N/A (closed product, no repo)
- What it stores: ChatGPT-side persistent user memories (saved facts and preferences) plus API-side conversation state, vector-store file search, and session items. User controls via settings and delete; API users manage via session and store APIs.
- How it retrieves: automatic injection. Platform decides what prior memory or store chunk enters context; developer control is limited to toggles and store IDs.
- Where the LLM is called: fully managed and opaque. Extraction, ranking, and injection all happen inside OpenAI infra with no hooks for custom scoring.
- Pricing/self-host story: no self-host. Billed as part of ChatGPT subscription (user side) and token/store usage on API side. Exact memory-specific prices NOT VERIFIED.
- Top weakness: lock-in plus opacity. No export of the memory model, no custom retrieval policy, privacy surface (memory retained by default), and impossible to benchmark or swap the curation logic.

## 6. Chroma / Weaviate backed DIY stacks

- Stars: Chroma 29.3k, Weaviate 16.8k (both verified from GitHub page extracts)
- What it stores: you decide. Embeddings plus documents, metadata, and (Weaviate) objects with structured fields. Chroma adds multimodal rows; Weaviate adds cloud-native replication and filtered object store. Neither has a native user/session/fact schema.
- How it retrieves: dense plus sparse plus hybrid search, metadata filtering, full-text and regex (Chroma), low-level query/get APIs. You compose recall, rerank, and injection yourself.
- Where the LLM is called: nowhere by default. Embeddings model is pluggable (OpenAI, Cohere, HF, sentence-transformers). Any extraction, summarization, or rerank LLM is code you add.
- Pricing/self-host story: both OSS. Chroma is Apache 2.0, runs in-memory, local persist, docker, or Chroma Cloud (serverless, $5 free credits per README). Weaviate is OSS with self-host and Weaviate Cloud options; exact license file and cloud prices NOT VERIFIED.
- Top weakness: fast to start, slow to finish as memory. No fact lifecycle, no invalidation, no temporal graph, no agent curation. Every memory behavior (dedup, expiry, promotion) is hand-built and usually stops at cosine top-k.

## Comparison: who already does judgment or reranking vs who burns LLM for everything

Judgment here means a cheap, typed, calibrated keep/drop/rank decision at retrieval time, separate from generation. None of the six does that in the Jev sense (choice/score/noul with probabilities, 70-500ms, no text generation).

- Closest to ranking without full LLM: Chroma/Weaviate (hybrid dense+sparse plus metadata filters) and Zep (graph validity intervals plus context-block assembly). Both still rank by similarity or recency, not by calibrated decision scores.
- Burns LLM per memory op: Mem0 (extract on write, rewrite on read), Zep ingest (entity extraction plus invalidation), Letta always (agent rewrites its own blocks), OpenAI memory (opaque managed calls).
- Puts the choice on the developer: LangGraph/LangMem and DIY vector stacks make zero judgment calls themselves. Flexible, but the default everyone ships is cosine top-k stuffed into the prompt, which is how Honcho-style contextToken budgets get burned.
- The gap Jev-memory targets: a typed judgment step between retrieve and inject that scores candidates and spends the token budget only on winners, instead of LLM-extract-everything (Mem0/Zep), LLM-curate-everything (Letta/OpenAI), or rank-by-cosine-and-hope (DIY/LangGraph-default).
