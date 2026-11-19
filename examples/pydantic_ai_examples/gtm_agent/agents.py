"""Agent factories for the GTM agent.

One reusable orchestrator Agent plus SubAgents delegates, following
the source Deep Agents example. The orchestrator delegates research
first, then writes the strategy. The researcher writes its full
report to the workspace and returns concise extracts.

Model ids are the source ids. One third-party source claims
gpt-5.4-nano was deprecated 2026-10-01 with shutdown 2027-04-01 and
replacement gpt-6-luna. That claim is not verified against OpenAI, so
the source ids stay. Do not switch models on that claim alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Caching, LocalWorkspace
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import FileSystem, Skills, SubAgent, SubAgents
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    SummarizingCompaction,
    TieredCompaction,
)
from pydantic_ai_harness.memory import FileMemoryStore, Memory
from pydantic_ai_harness.planning import Planning
from pydantic_ai_harness.spend_limits import Budget, SpendLimits
from pydantic_ai_harness.step_persistence import StepPersistence, StepStore
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits

if TYPE_CHECKING:
    from .tasks import TaskQueue

from .models import (
    REPORT_PUBLIC_PATH,
    REPORT_WORKSPACE_PATH,
    ContentBrief,
    ContentDeliverable,
    GtmDeps,
    GtmStrategy,
    MarketReport,
)

SUPERVISOR_MODEL = 'openai:gpt-5.4-nano'
RESEARCHER_MODEL = 'openai:gpt-5.4-mini'
CONTENT_WRITER_MODEL = 'openai:gpt-5.4-mini'

### [researcher-instructions]
RESEARCHER_INSTRUCTIONS = """You are a market research specialist. Your job is to gather and synthesize market data to support go-to-market decisions.

## Focus areas

- Market sizing: TAM, SAM, SOM estimates with methodology
- Competitor analysis: Product positioning, pricing, market share
- Audience segmentation: Demographics, psychographics, buying behavior
- Trend analysis: Industry trends, emerging technologies, regulatory changes

## Output

Write a thorough markdown report with methodology, detailed findings
per topic, and actionable recommendations for the GTM strategy. Save
it with the save_market_report tool. Then return the structured
report: concise extracts from the full report, and the file path in
full_report_path.

## Guidelines

- Cite sources when possible.
- Distinguish between hard data and estimates.
- Flag areas of uncertainty or where more research is needed.
- Keep analysis focused on what is actionable for go-to-market planning.
"""
### [/researcher-instructions]

### [orchestrator-instructions]
ORCHESTRATOR_INSTRUCTIONS = """You are a go-to-market strategy agent that helps teams plan and execute product launches.

## Capabilities

You coordinate between specialized subagents:

- market-researcher (sync): Delegates market research tasks — competitor analysis, TAM/SAM/SOM estimation, and audience segmentation.
- content creation (async): Start long-running content creation tasks — blog posts, landing pages, and marketing copy — with the start_content_task tool. The content-writer is not a delegate. Never call delegate_task for content.

## Workflow

1. When given a product or feature to launch, start by delegating market research to the market-researcher subagent.
2. Use the research findings to develop a GTM strategy covering positioning, pricing, and channel selection.
3. Kick off content creation tasks with the start_content_task tool for any required marketing materials. Each call takes one content brief and runs in the background.
4. Monitor async tasks and integrate deliverables into the final GTM plan.

## Guidelines

- Always ground recommendations in research data from the market-researcher.
- Present strategies with clear rationale and supporting evidence. Every rationale item must cite researcher evidence, and evidence_refs must list the report path.
- When creating content briefs for start_content_task, include target audience, key messages, and tone guidelines.
"""


### [/orchestrator-instructions]
def skills_dir() -> Path:
    """Directory holding the ported SKILL.md files."""
    return Path(__file__).parent / 'skills'


### [researcher]
def build_researcher_agent(
    workspace: Path,
    model: str | object | None = None,
    capabilities: Sequence | None = None,
) -> Agent[GtmDeps, MarketReport]:
    """Build the market-researcher delegate.

    The researcher writes its full report with the save_market_report
    tool and returns concise extracts as a MarketReport.
    """
    agent = Agent(
        model or RESEARCHER_MODEL,
        name='market-researcher',
        instructions=RESEARCHER_INSTRUCTIONS,
        deps_type=GtmDeps,
        output_type=MarketReport,
        capabilities=list(
            capabilities
            if capabilities is not None
            else [
                Caching(),
                LocalWorkspace(workspace),
                FileSystem(),
                Skills(skills_dir(), include=['analyze-market']),
            ]
        ),
    )

    @agent.tool
    def save_market_report(ctx: RunContext[GtmDeps], content: str) -> str:
        """Save the full markdown market research report.

        Writes to the fixed report path in the workspace and returns
        the path the parent agent records in full_report_path.
        """
        path = Path(workspace) / REPORT_WORKSPACE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return REPORT_PUBLIC_PATH

    return agent


### [/researcher]
### [content-writer]
def build_content_writer_agent(
    workspace: Path,
    task_id: str,
    brief: ContentBrief,
    model: str | object | None = None,
    capabilities: Sequence | None = None,
) -> Agent[GtmDeps, ContentDeliverable]:
    """Build the content-writer delegate for one brief.

    The writer is authored, not ported: the source example has no
    content-writer files. It reads the source report, writes one
    deliverable with the save_content tool, and returns its path.
    """
    instructions = f"""You are a content writer for go-to-market materials.

## Brief

- Kind: {brief.kind}
- Audience: {brief.audience}
- Key messages: {'; '.join(brief.key_messages) or 'none given'}
- Tone: {brief.tone}

## Workflow

1. Read the source report at {brief.source_report_path} for facts. Do not invent claims the report does not support.
2. Write one {brief.kind} deliverable with the save_content tool.
3. Return the deliverable path and a one-sentence summary.

## Guidelines

- Match the tone in the brief.
- Keep the deliverable focused on the audience and key messages.
- Cite the report for any factual claim.
"""
    agent = Agent(
        model or CONTENT_WRITER_MODEL,
        name='content-writer',
        instructions=instructions,
        deps_type=GtmDeps,
        output_type=ContentDeliverable,
        capabilities=list(
            capabilities
            if capabilities is not None
            else [
                Caching(),
                LocalWorkspace(workspace),
                FileSystem(),
            ]
        ),
    )

    @agent.tool
    def save_content(ctx: RunContext[GtmDeps], content: str) -> str:
        """Save the deliverable markdown and return its workspace path."""
        path = Path(workspace) / 'content' / f'{task_id}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return f'content/{task_id}.md'

    return agent


### [/content-writer]
### [orchestrator]
def build_orchestrator_agent(
    workspace: Path,
    researcher: Agent | None = None,
    model: str | object | None = None,
    capabilities: Sequence | None = None,
    task_queue: TaskQueue | None = None,
) -> Agent[GtmDeps, GtmStrategy]:
    """Build the GTM orchestrator with the researcher as a delegate.

    When a task queue is given, the orchestrator also gets a
    start_content_task tool that enqueues a content brief, starts it
    in the background, and returns its task id, mirroring the source
    start_async_task tool.
    """
    researcher = researcher or build_researcher_agent(workspace)
    agent = Agent(
        model or SUPERVISOR_MODEL,
        name='gtm-agent',
        instructions=ORCHESTRATOR_INSTRUCTIONS,
        deps_type=GtmDeps,
        output_type=GtmStrategy,
        capabilities=list(
            capabilities
            if capabilities is not None
            else [
                Caching(),
                LocalWorkspace(workspace),
                Skills(skills_dir(), include=['competitor-analysis']),
                SubAgents(
                    agents=[
                        SubAgent(
                            researcher,
                            name='market-researcher',
                            description=(
                                'Researches market trends, competitors, and '
                                'target audiences to inform GTM strategy'
                            ),
                        )
                    ]
                ),
            ]
        ),
    )

    if task_queue is not None:
        queue = task_queue

        @agent.tool
        async def start_content_task(
            ctx: RunContext[GtmDeps], brief: ContentBrief
        ) -> str:
            """Enqueue a content brief, start it, return its task id."""
            task = queue.create_task(brief, user_id=ctx.deps.user_id)
            queue.start_task(task.id)
            return task.id

    return agent


### [/orchestrator]
def build_gtm_agents(
    workspace: Path,
    task_queue: TaskQueue | None = None,
) -> tuple[Agent[GtmDeps, GtmStrategy], Agent[GtmDeps, MarketReport]]:
    """Build the orchestrator and researcher pair for one workspace."""
    researcher = build_researcher_agent(workspace)
    orchestrator = build_orchestrator_agent(
        workspace, researcher=researcher, task_queue=task_queue
    )
    return orchestrator, researcher


def _context_capabilities() -> list:
    """Context management shared by both agents.

    TieredCompaction mirrors the source: summarize at 0.85 of the
    context window, clearing tool results first. ToolOutputLimits
    spills oversized tool returns instead of dropping them.
    """
    return [
        TieredCompaction(
            tiers=[
                ClearToolResults(max_fraction=0.7),
                SummarizingCompaction(),
            ],
            target_fraction=0.85,
        ),
        ToolOutputLimits(),
    ]


def _spend_capabilities(spend_usd: Decimal | None) -> list:
    if spend_usd is None:
        return []
    return [SpendLimits(budgets=[Budget(usd=spend_usd, window='day')])]


### [production]
def build_production_agents(
    workspace: Path,
    task_queue: TaskQueue | None = None,
    orchestrator_model: str | object | None = None,
    researcher_model: str | object | None = None,
    spend_usd: Decimal | None = Decimal('10'),
    step_store: StepStore | None = None,
) -> tuple[Agent[GtmDeps, GtmStrategy], Agent[GtmDeps, MarketReport]]:
    """Build the pair with the full capability stack.

    Memory, planning, compaction, output limits, and spend limits are
    added here, on top of the base capabilities. When a step store is
    given, each agent gets its own StepPersistence instance, placed
    before TieredCompaction, because persistence must see history
    before compaction rewrites it.
    """
    memory_dir = Path(workspace) / '.agent-memory'
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_store = FileMemoryStore('.', workspace=LocalWorkspaceBackend(memory_dir))
    researcher_persistence = (
        [StepPersistence(store=step_store, agent_name='market-researcher')]
        if step_store is not None
        else []
    )
    orchestrator_persistence = (
        [StepPersistence(store=step_store, agent_name='gtm-agent')]
        if step_store is not None
        else []
    )
    researcher = build_researcher_agent(
        workspace,
        model=researcher_model,
        capabilities=[
            Caching(),
            LocalWorkspace(workspace),
            FileSystem(),
            Skills(skills_dir(), include=['analyze-market']),
            Memory(memory_store, agent_name='market-researcher'),
            *researcher_persistence,
            *_context_capabilities(),
            *_spend_capabilities(spend_usd),
        ],
    )
    orchestrator = build_orchestrator_agent(
        workspace,
        researcher=researcher,
        model=orchestrator_model,
        capabilities=[
            Caching(),
            LocalWorkspace(workspace),
            Skills(skills_dir(), include=['competitor-analysis']),
            SubAgents(
                agents=[
                    SubAgent(
                        researcher,
                        name='market-researcher',
                        description=(
                            'Researches market trends, competitors, and '
                            'target audiences to inform GTM strategy'
                        ),
                    )
                ]
            ),
            Planning(),
            Memory(memory_store, agent_name='gtm-agent'),
            *orchestrator_persistence,
            *_context_capabilities(),
            *_spend_capabilities(spend_usd),
        ],
        task_queue=task_queue,
    )
    return orchestrator, researcher


### [/production]
