"""Phase 4 tests: memory, planning, compaction, limits, spend."""

from __future__ import annotations

from pathlib import Path

import pytest

from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_examples.gtm_agent.agents import build_production_agents
from pydantic_ai_examples.gtm_agent.models import (
    REPORT_WORKSPACE_PATH,
    GtmDeps,
    GtmStrategy,
)
from pydantic_ai_harness.memory import FileMemoryStore, Memory

from .test_parity import (
    PROMPTS,
    scripted_orchestrator_model,
    scripted_researcher_model,
)

# Scripted models have no price, so SpendLimits warns; expected in tests.
pytestmark = pytest.mark.filterwarnings(
    'ignore::pydantic_ai_harness.spend_limits.UnpricedModelWarning'
)


async def test_production_stack_runs_offline(tmp_path: Path) -> None:
    orchestrator, _ = build_production_agents(
        tmp_path,
        orchestrator_model=scripted_orchestrator_model(),
        researcher_model=scripted_researcher_model(),
    )
    result = await orchestrator.run(PROMPTS[0], deps=GtmDeps(user_id='test'))
    assert isinstance(result.output, GtmStrategy)
    assert result.output.evidence_refs
    assert (tmp_path / REPORT_WORKSPACE_PATH).is_file()


async def test_memory_persists_across_runs(tmp_path: Path) -> None:
    memory_dir = tmp_path / 'memory'
    memory_dir.mkdir(parents=True, exist_ok=True)
    store = FileMemoryStore('.', workspace=LocalWorkspaceBackend(memory_dir))
    calls = {'n': 0}
    seen: list[str] = []

    async def write_fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if calls['n'] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        'write_memory',
                        {'content': 'The user prefers concise plans.'},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart('ok')])

    async def read_fn(messages: list, info: AgentInfo) -> ModelResponse:
        for message in messages:
            for part in getattr(message, 'parts', []):
                seen.append(repr(part))
        return ModelResponse(parts=[TextPart('ok')])

    writer = Agent(
        FunctionModel(write_fn),
        name='writer',
        output_type=str,
        capabilities=[LocalWorkspace(tmp_path), Memory(store, agent_name='t')],
    )
    await writer.run('remember this', deps=None)
    reader = Agent(
        FunctionModel(read_fn),
        name='reader',
        output_type=str,
        capabilities=[LocalWorkspace(tmp_path), Memory(store, agent_name='t')],
    )
    await reader.run('what do you remember?', deps=None)
    assert any('concise plans' in text for text in seen)


def test_production_agents_expose_planning_tools(tmp_path: Path) -> None:
    model = TestModel(call_tools=[])
    orchestrator, _ = build_production_agents(
        tmp_path, orchestrator_model=model, researcher_model=model
    )
    orchestrator.run_sync(PROMPTS[0], deps=GtmDeps(user_id='test'))
    names = {t.name for t in model.last_model_request_parameters.function_tools}
    assert 'write_plan' in names
    assert 'write_memory' in names
    assert 'delegate_task' in names
