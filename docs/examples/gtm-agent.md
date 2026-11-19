---
description: "Build a go-to-market strategy agent with Pydantic AI Harness: a migration of LangChain's Deep Agents deploy-gtm-agent example, with a market-researcher delegate, typed strategy output, async content tasks, and a FastAPI service."
---

# GTM Agent

This example builds a go-to-market (GTM) strategy agent: give it a product or feature to launch, and it researches the market, writes a GTM strategy grounded in that research, and drafts marketing content in the background. It is a migration of the LangChain Deep Agents [`deploy-gtm-agent`](https://github.com/langchain-ai/deepagents/tree/main/examples/deploy-gtm-agent) example to Pydantic AI Harness, keeping the source's contracts: the researcher writes its full report to the same workspace path, research runs synchronously before the strategy, and content creation runs as an async task the orchestrator monitors.

## What it does

- Delegates market research to a `market-researcher` subagent, which writes a full markdown report to the workspace and returns concise extracts.
- Writes a GTM strategy (positioning, pricing, channels) as a typed `GtmStrategy`, with every rationale item citing researcher evidence.
- Kicks off content creation (blog post, landing page, or marketing copy) as async tasks through a `start_content_task` tool, and tracks each task through a state machine.
- Persists run history with `StepPersistence` (SQLite locally, Postgres in deployment) and serves the agent over HTTP.

## Prerequisites

You need an OpenAI API key, and the repo checked out with dependencies installed:

```bash
uv sync --extra examples
cp examples/pydantic_ai_examples/gtm_agent/.env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Only that key is required to run the agent for real; `DATABASE_URL` selects Postgres persistence (SQLite is the default), and `LOGFIRE_TOKEN` turns on Logfire tracing.

## Run it

Start the service on port 8000:

```bash
uv run -m pydantic_ai_examples.gtm_agent
```

Create a GTM plan:

```bash
curl -X POST http://localhost:8000/plans \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Build a GTM plan for our new Python SDK for AI agents", "user_id": "you"}'
```

The response holds the strategy, the report path, and any content tasks. Fetch the research report with `GET /threads/{thread_id}/report`.

## The code

The example lives in `examples/pydantic_ai_examples/gtm_agent/`.

### Models

The data shapes come first. `MarketReport` is the researcher's concise extract from its full markdown report; `GtmStrategy` is the orchestrator's output, and `grounding_violations()` flags rationale items that cite no researcher evidence.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/models.py" fragment="market-report strategy"}```

Content briefs and tasks own the async content work. A task is a state machine: `pending` → `running` → `success` | `error` | `timeout` | `cancelled`.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/models.py" fragment="content grounding"}```

### Agents

The market-researcher delegate writes its full report with the `save_market_report` tool and returns the extracts as a `MarketReport`. It loads the ported `analyze-market` skill through the [`Skills`][pydantic_ai_harness.Skills] capability.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/agents.py" fragment="researcher"}```

The orchestrator delegates research first, then writes the strategy. It loads the ported `competitor-analysis` skill and the researcher through [`SubAgents`][pydantic_ai_harness.SubAgents]. When a task queue is given, it also gets a `start_content_task` tool that enqueues a brief and starts it in the background, mirroring the source's `start_async_task` tool.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/agents.py" fragment="orchestrator"}```

`build_production_agents()` adds the full capability stack on top: `Memory`, `Planning`, `TieredCompaction` (summarize at 0.85 of the context window, mirroring the source), `ToolOutputLimits`, and `SpendLimits`. When a step store is given, each agent gets its own `StepPersistence` instance, placed before `TieredCompaction` so persistence sees history before compaction rewrites it.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/agents.py" fragment="production"}```

### Async content tasks

The application owns the queue: content creation is a background worker, not model-controlled delegation, so it lives here instead of in a Harness capability. The orchestrator only enqueues briefs; the queue runs the content-writer agent for each one. The content-writer itself is authored, not ported — the source example has no content-writer files.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/tasks.py" fragment="queue"}```

### Persistence

`StepPersistence` records message history only. SQLite is the local store; Postgres is wired for deployment, with the caller owning the `asyncpg` pool. Resume from an interrupted snapshot only when no tool effect is unresolved.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/persistence.py" fragment="stores resume"}```

### Service

The native shape is `POST /plans`, which runs the orchestrator and returns the strategy. A missing model key maps to a 503 with a clear message instead of a 500.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/service.py" fragment="requests plans"}```

The legacy LangGraph SDK shape (`POST /threads` and `POST /threads/{thread_id}/runs`) is a thin adapter over the same run. It is temporary: delete it once callers move to `/plans`.

```snippet {path="/examples/pydantic_ai_examples/gtm_agent/service.py" fragment="legacy"}```

## Migration mapping

| Deep Agents (source) | Pydantic AI Harness (this example) |
|---|---|
| `create_deep_agent` | One reusable [`Agent`][pydantic_ai.Agent] + capabilities |
| `task` tool with `subagent_type="market-researcher"` | [`SubAgents`][pydantic_ai_harness.SubAgents] with `delegate_task` |
| `write_file` report at `/memories/subagents/market-researcher/market-research-report.md` | [`FileSystem`][pydantic_ai_harness.FileSystem] + `save_market_report` tool, same path |
| Async subagent (`start_async_task`) | Application `TaskQueue` + `start_content_task` tool |
| `StateBackend` files | [`StepPersistence`][pydantic_ai_harness.step_persistence.StepPersistence] (SQLite local, Postgres in deployment) |
| Summarization middleware | `TieredCompaction` + `ToolOutputLimits` |
| LangGraph SDK threads/runs | `POST /plans`; legacy `/threads` adapter kept for deletion |
| No output schema | `output_type=MarketReport` / `GtmStrategy` |
| No web search wired in | None in phase 1; `ExaSearch` is a phase-2 option |

## Notes

!!! note "Model ids"
    The supervisor runs `openai:gpt-5.4-nano` and the researcher and content-writer run `openai:gpt-5.4-mini` — the exact ids from the source example. One third-party source claims `gpt-5.4-nano` was deprecated 2026-10-01 with shutdown 2027-04-01 and replacement `gpt-6-luna`. A live check on 19 Nov 2026 found `gpt-5.4-nano` listed in `/v1/models` and running as the supervisor, so it is available now and the source ids stay; the 2027 shutdown date is still unverified.

The example's tests live in `gtm_agent/tests/` and run with scripted models, so they need no API key. The repo suite does not collect example-package tests (the Slack lead qualifier example has no test file either; its code is exercised through docs fences), so run them directly:

```bash
uv run --all-packages --all-extras pytest examples/pydantic_ai_examples/gtm_agent/tests -q
```
