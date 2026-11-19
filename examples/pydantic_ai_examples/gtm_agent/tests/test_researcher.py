"""Researcher delegate tests: report file contract and typed output."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_examples.gtm_agent.agents import build_researcher_agent
from pydantic_ai_examples.gtm_agent.models import (
    REPORT_PUBLIC_PATH,
    REPORT_WORKSPACE_PATH,
    GtmDeps,
)

REPORT_MD = """# Market Research Report: Python SDK for AI agents

## Methodology
Sized from public package registries and vendor pricing pages.

## Findings
The market is growing fast. Competitors include LangChain and LlamaIndex.
"""

REPORT_FIELDS = {
    'full_report_path': REPORT_PUBLIC_PATH,
    'tam_sam_som': 'TAM $2B, SAM $400M, SOM $40M. Methodology: public registries.',
    'competitors': ['LangChain', 'LlamaIndex'],
    'audiences': ['AI platform teams'],
    'trends': ['Agents are the default interface'],
    'uncertainties': ['Pricing data is estimated'],
}


def scripted_researcher_model() -> FunctionModel:
    """First call saves the report, second returns the structured report."""
    calls = {'n': 0}

    async def fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if calls['n'] == 1:
            return ModelResponse(
                parts=[ToolCallPart('save_market_report', {'content': REPORT_MD})]
            )
        return ModelResponse(parts=[ToolCallPart('final_result', dict(REPORT_FIELDS))])

    return FunctionModel(fn)


def test_report_path_contract() -> None:
    assert REPORT_PUBLIC_PATH == (
        '/memories/subagents/market-researcher/market-research-report.md'
    )


async def test_researcher_writes_report_and_returns_extracts(tmp_path: Path) -> None:
    researcher = build_researcher_agent(tmp_path, model=scripted_researcher_model())
    result = await researcher.run(
        'Research the market for a new Python SDK for AI agents',
        deps=GtmDeps(user_id='test'),
    )
    report = result.output
    assert report.full_report_path == REPORT_PUBLIC_PATH
    assert report.competitors == ['LangChain', 'LlamaIndex']
    assert 'TAM' in report.tam_sam_som
    path = tmp_path / REPORT_WORKSPACE_PATH
    assert path.is_file()
    assert path.read_text(encoding='utf-8') == REPORT_MD


async def test_researcher_run_is_deterministic(tmp_path: Path) -> None:
    researcher = build_researcher_agent(tmp_path, model=scripted_researcher_model())
    first = await researcher.run('Research X', deps=GtmDeps(user_id='test'))
    second = await researcher.run('Research X', deps=GtmDeps(user_id='test'))
    assert first.output == second.output
