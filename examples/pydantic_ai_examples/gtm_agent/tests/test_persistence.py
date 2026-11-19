"""Phase 5 tests: StepPersistence with SQLite, resume, fork."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pydantic_ai_examples.gtm_agent.agents import build_production_agents
from pydantic_ai_examples.gtm_agent.models import REPORT_WORKSPACE_PATH, GtmDeps
from pydantic_ai_examples.gtm_agent.persistence import (
    fork_history,
    resume_history,
    sqlite_store,
    unresolved_effects,
)

from .test_parity import (
    PROMPTS,
    scripted_orchestrator_model,
    scripted_researcher_model,
)


async def test_sqlite_persistence_records_and_resumes(tmp_path: Path) -> None:
    store = sqlite_store(tmp_path / 'runs.db')
    orchestrator, _ = build_production_agents(
        tmp_path,
        orchestrator_model=scripted_orchestrator_model(),
        researcher_model=scripted_researcher_model(),
        step_store=store,
    )
    result = await orchestrator.run(
        PROMPTS[0], deps=GtmDeps(user_id='test'), conversation_id='conv-1'
    )
    assert result.output.positioning
    assert (tmp_path / REPORT_WORKSPACE_PATH).is_file()

    runs = await store.list_runs(conversation_id='conv-1')
    assert runs, 'no runs recorded'
    run_id = runs[-1].run_id

    assert await unresolved_effects(store, run_id) == []
    history = await resume_history(store, run_id)
    assert history, 'resumed history is empty'

    continued = await orchestrator.run(
        'Now add a pricing note',
        deps=GtmDeps(user_id='test'),
        conversation_id='conv-1',
        message_history=history,
    )
    assert continued.output.positioning


async def test_fork_returns_same_history(tmp_path: Path) -> None:
    store = sqlite_store(tmp_path / 'runs.db')
    orchestrator, _ = build_production_agents(
        tmp_path,
        orchestrator_model=scripted_orchestrator_model(),
        researcher_model=scripted_researcher_model(),
        step_store=store,
    )
    await orchestrator.run(
        PROMPTS[0], deps=GtmDeps(user_id='test'), conversation_id='conv-1'
    )
    runs = await store.list_runs(conversation_id='conv-1')
    run_id = runs[-1].run_id
    assert await resume_history(store, run_id) == await fork_history(store, run_id)


@pytest.mark.skipif(
    not os.environ.get('DATABASE_URL'),
    reason='needs DATABASE_URL pointing at a Postgres server',
)
async def test_postgres_store_records_runs(tmp_path: Path) -> None:
    from pydantic_ai_examples.gtm_agent.persistence import postgres_store

    store, pool = await postgres_store(os.environ['DATABASE_URL'])
    try:
        orchestrator, _ = build_production_agents(
            tmp_path,
            orchestrator_model=scripted_orchestrator_model(),
            researcher_model=scripted_researcher_model(),
            step_store=store,
        )
        await orchestrator.run(
            PROMPTS[0], deps=GtmDeps(user_id='test'), conversation_id='conv-1'
        )
        runs = await store.list_runs(conversation_id='conv-1')
        assert runs
    finally:
        await pool.close()
