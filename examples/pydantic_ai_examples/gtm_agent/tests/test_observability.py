"""Observability tests: Logfire configures once and no-token runs work."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from logfire.testing import CaptureLogfire

import pydantic_ai_examples.gtm_agent.service as service
from pydantic_ai_examples.gtm_agent.persistence import sqlite_store
from pydantic_ai_examples.gtm_agent.service import (
    configure_observability,
    create_app,
)

from .test_content_tasks import writer_model
from .test_parity import (
    PROMPTS,
    scripted_orchestrator_model,
    scripted_researcher_model,
)

# Scripted models have no price, so SpendLimits warns; expected in tests.
pytestmark = pytest.mark.filterwarnings(
    'ignore::pydantic_ai_harness.spend_limits.UnpricedModelWarning'
)


def test_configure_observability_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv('LOGFIRE_TOKEN', raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(service, '_observability_configured', None)
    with caplog.at_level(logging.WARNING):
        first = configure_observability()
        second = configure_observability()
    assert first is False
    assert second is False
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and 'Logfire' in record.message
    ]
    assert len(warnings) == 1


async def test_no_token_boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv('LOGFIRE_TOKEN', raising=False)
    monkeypatch.chdir(tmp_path)
    app = create_app(workspace_root=tmp_path / 'workspace')
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url='http://test'
    ) as client:
        response = await client.get('/health')
    assert response.status_code == 200


async def test_plan_run_emits_span_and_completion_log(
    capfire: CaptureLogfire, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pretend configuration already ran: calling configure_observability()
    # here would re-configure Logfire after capfire attached its exporter
    # and drop it. configure() itself is covered by the idempotency test.
    monkeypatch.setattr(service, '_observability_configured', False)
    app = create_app(
        workspace_root=tmp_path / 'workspace',
        orchestrator_model=scripted_orchestrator_model(),
        researcher_model=scripted_researcher_model(),
        content_writer_model=writer_model(),
        step_store=sqlite_store(tmp_path / 'runs.db'),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url='http://test'
    ) as client:
        response = await client.post(
            '/plans', json={'prompt': PROMPTS[0], 'user_id': 'test'}
        )
    assert response.status_code == 200
    thread_id = response.json()['thread_id']
    spans = capfire.exporter.exported_spans
    # A span is exported twice (pending, then completed); assert on the
    # completed one only.
    plan_spans = [
        span
        for span in spans
        if span.name == 'Run GTM plan {thread_id}'
        and (span.attributes or {}).get('logfire.span_type') == 'span'
        and (span.attributes or {}).get('thread_id') == thread_id
    ]
    assert len(plan_spans) == 1
    logs = [
        span
        for span in spans
        if span.name == 'Plan complete {thread_id}'
        and (span.attributes or {}).get('logfire.span_type') == 'log'
        and (span.attributes or {}).get('thread_id') == thread_id
    ]
    assert len(logs) == 1
    log_attrs = logs[0].attributes or {}
    assert log_attrs['grounding_violations'] == 0
