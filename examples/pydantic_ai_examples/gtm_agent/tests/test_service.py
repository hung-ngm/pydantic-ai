"""Phase 6 tests: HTTP service and legacy thread/run adapter."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from httpx import ASGITransport

from pydantic_ai_examples.gtm_agent.models import REPORT_PUBLIC_PATH
from pydantic_ai_examples.gtm_agent.persistence import sqlite_store
from pydantic_ai_examples.gtm_agent.service import create_app

from .test_content_tasks import writer_model
from .test_parity import (
    PROMPTS,
    scripted_orchestrator_model,
    scripted_researcher_model,
)


def make_client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        workspace_root=tmp_path / 'workspace',
        orchestrator_model=scripted_orchestrator_model(),
        researcher_model=scripted_researcher_model(),
        content_writer_model=writer_model(),
        step_store=sqlite_store(tmp_path / 'runs.db'),
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url='http://test')


async def test_health(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


async def test_create_plan_returns_strategy_and_report(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        response = await client.post(
            '/plans', json={'prompt': PROMPTS[0], 'user_id': 'test'}
        )
    assert response.status_code == 200
    body = response.json()
    assert body['strategy']['positioning']
    assert body['grounding_violations'] == []
    assert body['report_path'] == REPORT_PUBLIC_PATH
    assert body['content_tasks'] == []
    thread_id = body['thread_id']

    async with make_client(tmp_path) as client:
        report = await client.get(f'/threads/{thread_id}/report')
    assert report.status_code == 200
    assert 'Market Research Report' in report.json()['content']


async def test_second_plan_on_thread_resumes(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        first = await client.post(
            '/plans', json={'prompt': PROMPTS[0], 'user_id': 'test'}
        )
        thread_id = first.json()['thread_id']
        second = await client.post(
            '/plans',
            json={
                'prompt': 'Now add a pricing note',
                'user_id': 'test',
                'thread_id': thread_id,
            },
        )
    assert second.status_code == 200
    assert second.json()['thread_id'] == thread_id
    assert second.json()['strategy']['positioning']


async def test_legacy_thread_run_adapter(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        thread = await client.post('/threads')
        assert thread.status_code == 200
        thread_id = thread.json()['thread_id']
        run = await client.post(
            f'/threads/{thread_id}/runs',
            json={
                'input': {
                    'messages': [
                        {'role': 'user', 'content': PROMPTS[0]},
                    ]
                }
            },
        )
    assert run.status_code == 200
    body = run.json()
    assert body['thread_id'] == thread_id
    strategy = json.loads(body['messages'][0]['content'])
    assert strategy['positioning']
    assert strategy['evidence_refs'] == [REPORT_PUBLIC_PATH]


async def test_legacy_run_without_user_message_is_400(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        thread = await client.post('/threads')
        thread_id = thread.json()['thread_id']
        run = await client.post(
            f'/threads/{thread_id}/runs',
            json={'input': {'messages': []}},
        )
    assert run.status_code == 400


async def test_tasks_endpoints(tmp_path: Path) -> None:
    async with make_client(tmp_path) as client:
        listing = await client.get('/threads/nope/tasks')
        assert listing.status_code == 200
        assert listing.json()['tasks'] == []
        cancel = await client.post('/threads/nope/tasks/nope/cancel')
        assert cancel.status_code == 404
        missing = await client.get('/threads/nope/report')
        assert missing.status_code == 404
