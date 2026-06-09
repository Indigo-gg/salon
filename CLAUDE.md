# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Salon** is a multi-agent dialogue collaboration system (Python 3.11+) where 3-5 AI agents with distinct personalities engage in deep, multi-round discussions. The core philosophy is "process is the output" — the conversation itself is more valuable than any final report. The first use case is philosophical dialogue.

This is currently a **pre-implementation design project** — it has documentation and configuration but no source code yet. The full architecture is defined in `docs/specification.md`.

## Tech Stack

- Python 3.11+, pip + `requirements.txt`
- LLM calls via OpenAI-compatible API (any provider)
- `httpx` for async HTTP, `pydantic` for structured output schemas, `pyyaml` for config
- File-system storage: JSON, JSONL, Markdown, YAML
- CLI interface (V1), planned FastAPI + HTML/CSS/JS web UI (V2)

## Commands (once implemented)

```bash
pip install -r requirements.txt
python -m src.main --config config/local.yaml --topic "自由意志是否存在？"
python -m src.main --config config/local.yaml --topic "意识的本质" --participants 4
python -m src.main --config config/local.yaml --topic "AI伦理" --human-role chair
```

## Architecture

The system is organized around these layers:

**Entry**: `src/main.py` → **Orchestrator** (`src/core/orchestrator.py`) — main controller with state machine (CREATED → RUNNING → PAUSED → WRAPPING_UP → FINISHED). Runs the loop: check human input → schedule speaker → build prompt → call LLM → parse output → post-process.

**Core engine** (`src/core/`):
- `scheduler.py` — Weighted scoring for organic speaking order (not round-robin). Factors: silence duration, mentions, direct questions, self-assessed relevance.
- `context_manager.py` — Assembles prompts within a ~12K token budget across layers: System Prompt + Soul → Archive → Whiteboard → Notebook → Summarized history → Recent messages → Action prompt.
- `session.py` — Session lifecycle management.

**Agent system** (`src/agents/`):
- `base.py` — BaseAgent with `generate_intent()` and `speak()` methods. Structured output: `SpeechOutput` (speech, speech_type, mentions, notebook_update) and `SpeakIntent` (summary, relevance, intent_type, target).
- `moderator.py` — Socrates-inspired. Topic exhaustion checks (CONTINUE/DEEP_DIVE/TRANSITION), mid-discussion summaries.
- `participant.py` — Follows "steel-manning" and "constructive follow-up" principles.
- `scribe.py` — Low-frequency speaker (~every 5-8 rounds). Maintains whiteboard, detects undercurrents.
- `soul.py` — Loads personality profiles from `config/souls/*.md`.

**Four-layer memory** (`src/memory/`):
1. **Conversation Stream** (`stream.py`) — Sliding window, last 12 messages full, older summarized in batches of 5.
2. **Personal Notebook** (`notebook.py`) — Private per-agent: core_stance, pending_responses, expressed_points, learned_from_others, evolution_summary.
3. **Shared Whiteboard** (`whiteboard.py`) — Shared state: current_topic, consensus, disagreements, parked, to_explore, surprises.
4. **Archive** (`archive.py`) + **Retrieval** (`retrieval.py`) — Cross-session persistent memory with keyword/semantic/hybrid retrieval.

**Human interaction** (`src/human/`): Three modes — chair, participant, observer (default). Commands: /pause, /resume, /ask, /topic, /summarize, /whiteboard, /notebook, /end, /inject, /skip, /status, /help.

**LLM client** (`src/llm/`): OpenAI-compatible with retry, timeout, structured output parsing.

**Output** (`src/output/`): Transcript (JSONL), notebook evolution snapshots, discussion digest (Markdown), final report (Markdown).

## Configuration

- `config/default.yaml` — All system parameters (LLM, discussion, scheduler weights, memory, context token budgets, human interaction, output, storage, logging).
- `config/souls/*.md` — Agent personality files (moderator, philosopher_east, philosopher_west, marxist, scientist, scribe).
- Local overrides: copy `default.yaml` to `local.yaml` and customize.

## Implementation Roadmap

V0.1 (MVP): Round-robin scheduling, basic conversation stream, CLI → V0.2: Weighted scheduling, notebooks → V0.3: Full memory + archive retrieval → V0.4: Polish → V1.0: Web UI (FastAPI + HTML/CSS/JS).
