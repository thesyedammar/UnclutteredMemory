# Track A: Agent Memory Failure Modes

Ranked by realness (strongest direct evidence first). Plain language. No invented numbers. Items marked NOT VERIFIED were not confirmed by a primary source in this pass.

## 1. Lost in the middle: buried context gets ignored
- Failure: Relevant fact in the middle of long context is missed even when it fits in the window.
- Who hits it: Any agent doing RAG or stuffing long histories, support bots, multi-doc QA.
- Evidence: U-shaped curve, best recall at start and end, worst in middle. Drop of 15-25 percentage points vs position 0%. With 20 documents, models scoring 70%+ with answer first dropped to under 50% with answer in middle. Sources: https://arxiv.org/abs/2307.03172 and https://pristren.com/blog/lost-in-middle-attention-paper/
- Why current fixes miss it: More context window does not fix position bias. Naive concat of retrieved chunks puts top hits in the middle. Re-ranking helps but most pipelines skip it.
- Honesty flags: Numbers above come from a secondary explainer summarizing Liu et al. 2023, not from re-reading the full paper tables in this pass. Exact per-model tables NOT VERIFIED here.

## 2. Memory poisoning and injection via stored memory
- Failure: Attacker plants a false fact in persistent memory through normal input, it silently steers future sessions.
- Who hits it: Personal assistants with memory-write plus email, calendar, or doc read. Stacks named: Mem0, Letta, A-Mem, ExpeL, MemoryOS, OpenClaw.
- Evidence: GhostWriter reports about 98% injection rate and about 60% activation rate across five frameworks and four LLM backends. MemGhost reports 87.5% end-to-end success on GPT-5.4 with OpenClaw and 71.4% on Claude Code SDK, plus concealment under direct questioning of 25.0% on Sonnet 4.5 and 7.1% on OpenClaw/GPT-5.4. Example payload: false Zelle daily limit of $10,000. Sources: https://arxiv.org/abs/2607.05189 and https://arxiv.org/abs/2607.06595 via summary at https://chatforest.com/builders-log/memghost-ghostwriter-ai-agent-memory-poisoning-email-injection-builder-security-guide/
- Why current fixes miss it: Write happens through the agent's own legitimate memory API, invisible in chat, then loads as trusted context with no provenance. OpenClaw policy treats prompt-injection-only chains as by design, per same summary.
- Honesty flags: Rates are from a secondary builder guide summarizing two July 6 2026 arXiv preprints. Primary paper tables NOT VERIFIED in this pass. No CVEs assigned per that guide. Defense numbers below are also from that guide.

## 3. Contradiction and stale facts pile up
- Failure: Old fact and corrected fact both retrieve, agent answers with the stale one or mixes both.
- Who hits it: Long-running agents, coaching apps, CRM and support agents, any append-only vector store over chat logs.
- Evidence: Extracted-fact and graph memory outperform naive RAG on LOCOMO by 20-40 percentage points. Mem0 reports about 26% accuracy gain over a strong RAG baseline on LOCOMO. Sources: https://aiworkflowlab.dev/article/agent-memory-mem0-vs-letta-vs-zep-2026 and https://mem0.ai/guide/ai-memory-tools-contradictions-outdated-information and https://arxiv.org/abs/2402.17753
- Why current fixes miss it: Pure vector search returns every mention of a topic, so a moved deadline or moved city competes with the old value. Fixes need active update, temporal supersession, or graph validity windows, which naive LangChain-style history does not do.
- Honesty flags: LOCOMO gain range and Mem0 26% claim are vendor and secondary-guide reports, methodology NOT VERIFIED here. LangChain-specific behavior NOT VERIFIED in this pass (no LangChain docs fetched).

## 4. Context bloat: full-history stuffing burns tokens and latency
- Failure: Re-sending full chat history each turn blows cost and latency and still hits limits.
- Who hits it: Teams without a memory layer, early prototypes, high-turn agents.
- Evidence: Mem0 reports cutting prompt tokens by up to 80% and using 90% fewer tokens than full-history dump. Letta-style stateful turns cost about 1.5-3x per-turn tokens vs stateless. Write latency p50 about 80-200 ms Mem0 async, 150-400 ms Letta sync core update, 300-800 ms Zep graph extraction. Sources: https://aiworkflowlab.dev/article/agent-memory-mem0-vs-letta-vs-zep-2026 and https://mem0.ai/guide/ai-memory-tools-contradictions-outdated-information
- Why current fixes miss it: Summarization alone keeps bloat or drops detail. Teams either over-stuff or over-trim with no budget control.
- Honesty flags: Token and latency figures are from vendor and secondary benchmark reports, NOT VERIFIED against independent repro. Honcho contextTokens budget behavior NOT VERIFIED from primary docs in this pass.

## 5. Junk persistence: trivia accumulates into noise
- Failure: Every turn gets saved, useful facts drown in trivia, recall precision drops.
- Who hits it: Always-on companions, coding agents with full logs, Mem0-style extractors without strict filters.
- Evidence: Same LOCOMO gap as above (20-40 points for fact vs naive chunk recall). Mem0 uses an LLM judge to decide update, replace, or add. Zep uses temporal invalidation. Letta relies on the agent to self-edit core and archival stores. Source: https://aiworkflowlab.dev/article/agent-memory-mem0-vs-letta-vs-zep-2026
- Why current fixes miss it: No forgetting policy means noise grows without bound. Manual curation does not scale. Bursty updates can cause double-writes if per-user writes are not serialized, per same guide.
- Honesty flags: Double-write failure mode is a practitioner report from that guide, NOT VERIFIED with a primary repro.

## 6. LLM-everything memory is slow and pricey
- Failure: Every read and write calls an LLM judge, extractor, or dual judges, adding latency and cost per turn.
- Who hits it: Production agents on Mem0, Letta, Zep, and any AM-Sentry S3 style defense with dual judges.
- Evidence: Latency ladder above (Mem0 lowest, Zep graph highest). AM-Sentry S3 plus retrieval screening drops average attack success below 12% except Llama at 20%, with minimal utility loss, but adds latency and LLM calls per memory op. Source: https://chatforest.com/builders-log/memghost-ghostwriter-ai-agent-memory-poisoning-email-injection-builder-security-guide/
- Why current fixes miss it: Security and quality screens make the cost worse. Teams must choose cheap and exposed or safe and slow, with no typed low-cost decision step.
- Honesty flags: AM-Sentry numbers are from the GhostWriter authors via the secondary guide, NOT VERIFIED from the primary paper here. Jev cost and latency comparison NOT VERIFIED in this file.

## 7. Reference point: Honcho shows the target shape
- Failure addressed: Unbounded injection with no budget or structure.
- Who uses it: Builders of stateful agents wanting query plus inject with representations, peer cards, and summaries.
- Evidence: Honcho repo at https://github.com/plastic-labs/honcho has 6.7k stars and 820 forks at time of fetch. Described as reasoning-first memory with background derivation of representations and peer cards, plus cheap non-LLM retrieval and LLM-powered interactive query.
- Why it still leaves room: Dialectic reasoning and background derivation still lean on LLM calls, with no machine-native typed judgment step. Exact contextTokens budget semantics NOT VERIFIED from the fetched snippet.
- Honesty flags: Star and fork counts are point-in-time. Card, representation, summary, two-layer injection, and contextTokens details come from the shared task background, NOT VERIFIED against Honcho docs in this pass.

## Retrieval log (8-call budget)
- Searches used (5): lost-in-middle paper, Honcho docs retry (first Honcho query returned spam, retried), Mem0 vs Letta vs Zep contradictions, memory injection security, Honcho github card contextTokens.
- Extracts used (3 calls, 6 URLs): arxiv abs 2307.03172, mem0 contradictions guide, chatforest MemGhost guide, pristren lost-in-middle explainer, aiworkflowlab comparison, honcho github repo.
- Not fetched: Letta docs, Zep docs, LangChain memory docs, primary arXiv PDFs for 2607.05189 and 2607.06595. Those gaps are flagged above.
