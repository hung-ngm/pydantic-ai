"""Parity tests: the orchestrator end to end, against the source prompts.

The three prompts come from the Deep Agents deploy-gtm-agent README.
Phase 1 runs the first prompt end to end with scripted models; phase 7
runs all three as fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_examples.gtm_agent.agents import (
    build_orchestrator_agent,
    build_researcher_agent,
)
from pydantic_ai_examples.gtm_agent.models import (
    REPORT_PUBLIC_PATH,
    REPORT_WORKSPACE_PATH,
    GtmDeps,
)

from .test_researcher import REPORT_FIELDS, REPORT_MD

PROMPTS = [
    "We're launching a new Python SDK for AI agents next month — build me a GTM plan",
    'Help us position our vector database product against Pinecone and Weaviate',
    "We're targeting mid-market engineering teams — what channels should we prioritize?",
]

STRATEGY_FIELDS = {
    'positioning': 'The SDK for teams shipping agents in production',
    'pricing': 'Free tier, then usage-based team pricing',
    'channels': ['Developer docs', 'Open source community'],
    'rationale': [
        'Positioning follows the researcher finding that teams value production readiness (see report).',
        'Pricing follows the competitor analysis in the report.',
    ],
    'evidence_refs': [REPORT_PUBLIC_PATH],
}


def scripted_researcher_model() -> FunctionModel:
    calls = {'n': 0}

    async def fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if calls['n'] == 1:
            return ModelResponse(
                parts=[ToolCallPart('save_market_report', {'content': REPORT_MD})]
            )
        return ModelResponse(parts=[ToolCallPart('final_result', dict(REPORT_FIELDS))])

    return FunctionModel(fn)


def scripted_orchestrator_model() -> FunctionModel:
    calls = {'n': 0}

    async def fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if calls['n'] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        'delegate_task',
                        {
                            'agent_name': 'market-researcher',
                            'task': 'Research the market for a new Python SDK for AI agents',
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[ToolCallPart('final_result', dict(STRATEGY_FIELDS))]
        )

    return FunctionModel(fn)


async def test_vertical_slice_first_prompt(tmp_path: Path) -> None:
    researcher = build_researcher_agent(tmp_path, model=scripted_researcher_model())
    orchestrator = build_orchestrator_agent(
        tmp_path,
        researcher=researcher,
        model=scripted_orchestrator_model(),
    )
    result = await orchestrator.run(PROMPTS[0], deps=GtmDeps(user_id='test'))
    strategy = result.output
    assert strategy.positioning
    assert strategy.pricing
    assert strategy.channels
    assert strategy.evidence_refs == [REPORT_PUBLIC_PATH]
    assert all('report' in item for item in strategy.rationale)
    report_path = tmp_path / REPORT_WORKSPACE_PATH
    assert report_path.is_file()
    assert report_path.read_text(encoding='utf-8') == REPORT_MD


def test_strategy_grounding_check() -> None:
    from pydantic import ValidationError

    from pydantic_ai_examples.gtm_agent.models import (
        GtmStrategy,
        MarketReport,
        grounding_violations,
    )

    grounded = GtmStrategy(**STRATEGY_FIELDS)
    assert grounding_violations(grounded) == []

    ungrounded = GtmStrategy(
        positioning='x',
        pricing='y',
        channels=['z'],
        rationale=['A claim with no citation at all.'],
        evidence_refs=[REPORT_PUBLIC_PATH],
    )
    assert len(grounding_violations(ungrounded)) == 1

    empty = GtmStrategy(positioning='x', pricing='y')
    assert len(grounding_violations(empty)) == 2

    with pytest.raises(ValidationError):
        MarketReport(full_report_path='/x.md')


@pytest.mark.parametrize('prompt', PROMPTS)
async def test_all_prompts_return_grounded_strategy(
    tmp_path: Path, prompt: str
) -> None:
    """Each README prompt returns a grounded strategy and a report."""
    researcher = build_researcher_agent(tmp_path, model=scripted_researcher_model())
    orchestrator = build_orchestrator_agent(
        tmp_path,
        researcher=researcher,
        model=scripted_orchestrator_model(),
    )
    result = await orchestrator.run(prompt, deps=GtmDeps(user_id='test'))
    from pydantic_ai_examples.gtm_agent.models import grounding_violations

    assert grounding_violations(result.output) == []
    assert result.output.evidence_refs == [REPORT_PUBLIC_PATH]
    assert (tmp_path / REPORT_WORKSPACE_PATH).is_file()


@pytest.mark.skipif(
    not os.environ.get('OPENAI_API_KEY'),
    reason='needs OPENAI_API_KEY for a live model run',
)
async def test_live_run_first_prompt(tmp_path: Path) -> None:
    """Optional live smoke test. Skipped without a key."""
    from pydantic_ai_examples.gtm_agent.agents import build_production_agents

    orchestrator, _ = build_production_agents(tmp_path)
    result = await orchestrator.run(PROMPTS[0], deps=GtmDeps(user_id='test'))
    assert result.output.positioning
    assert result.output.pricing
    assert result.output.channels
    assert (tmp_path / REPORT_WORKSPACE_PATH).is_file()
