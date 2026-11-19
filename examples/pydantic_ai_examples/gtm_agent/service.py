"""HTTP service boundary for the GTM agent.

Native shape: POST /plans runs the orchestrator and returns the
strategy. The legacy LangGraph SDK shape (POST /threads and
POST /threads/{thread_id}/runs) is a thin adapter over the same run.
The adapter is temporary: delete it once callers move to /plans.

Observability: Logfire configures once per process at startup
(`configure_observability`), with `send_to_logfire='if-token-present'`,
so runs without a token send nothing and proceed as normal. Each plan
run gets one span and one completion log. Tests and CI have no token,
so instrumentation must never block a run.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pydantic_ai.exceptions import UserError

from . import __version__
from .agents import build_production_agents
from .models import (
    REPORT_PUBLIC_PATH,
    REPORT_WORKSPACE_PATH,
    ContentTask,
    GtmDeps,
    GtmStrategy,
    grounding_violations,
)
from .persistence import StepStore, resume_history, sqlite_store
from .tasks import TaskQueue

logger = logging.getLogger(__name__)


_observability_configured: bool | None = None


def configure_observability() -> bool:
    """Configure Logfire once per process. Returns True if it sends.

    Always configures: with no token it sends nothing
    (`send_to_logfire='if-token-present'`) and logs one warning.
    Later calls return the first result without reconfiguring.
    """
    global _observability_configured
    if _observability_configured is not None:
        return _observability_configured
    import logfire

    logfire.configure(
        send_to_logfire='if-token-present',
        service_name='gtm-agent',
        service_version=__version__,
        environment=os.environ.get('GTM_ENVIRONMENT', 'dev'),
    )
    logfire.instrument_pydantic_ai()
    logfire.instrument_httpx(capture_all=True)
    _observability_configured = bool(
        os.environ.get('LOGFIRE_TOKEN') or Path('.logfire').exists()
    )
    if not _observability_configured:
        logger.warning(
            'Logfire is not configured: set LOGFIRE_TOKEN or run '
            '`uvx logfire-cli auth` and `uvx logfire-cli init` to record runs.'
        )
    return _observability_configured


### [requests]
class PlanRequest(BaseModel):
    """Native plan request."""

    prompt: str
    user_id: str
    thread_id: str | None = None


class PlanResponse(BaseModel):
    """Native plan response."""

    thread_id: str
    strategy: GtmStrategy
    grounding_violations: list[str]
    report_path: str | None
    content_tasks: list[ContentTask] = Field(default_factory=list)


class ThreadResponse(BaseModel):
    """Legacy adapter: a created thread."""

    thread_id: str


class RunRequest(BaseModel):
    """Legacy adapter: a run input in LangGraph SDK shape."""

    input: dict


### [/requests]
async def _run_plan(
    store: StepStore,
    workspace: Path,
    queue: TaskQueue,
    prompt: str,
    user_id: str,
    thread_id: str,
    orchestrator_model: str | object | None = None,
    researcher_model: str | object | None = None,
) -> PlanResponse:
    """Run one plan in a thread workspace, returning the response."""
    import logfire

    with logfire.span('Run GTM plan {thread_id}', thread_id=thread_id):
        orchestrator, researcher = build_production_agents(
            workspace,
            task_queue=queue,
            orchestrator_model=orchestrator_model,
            researcher_model=researcher_model,
            step_store=store,
        )
        history = None
        runs = await store.list_runs(conversation_id=thread_id)
        if runs:
            history = await resume_history(store, runs[-1].run_id)
        async with orchestrator, researcher:
            result = await orchestrator.run(
                prompt,
                deps=GtmDeps(user_id=user_id),
                conversation_id=thread_id,
                message_history=history,
            )
        violations = grounding_violations(result.output)
        logfire.info(
            'Plan complete {thread_id}',
            thread_id=thread_id,
            grounding_violations=len(violations),
        )
        report = workspace / REPORT_WORKSPACE_PATH
        return PlanResponse(
            thread_id=thread_id,
            strategy=result.output,
            grounding_violations=violations,
            report_path=REPORT_PUBLIC_PATH if report.is_file() else None,
            content_tasks=queue.list_tasks(),
        )


### [legacy]
def _register_legacy_routes(
    app: FastAPI,
    thread_workspace: Callable[[str], Path],
    run_plan_or_503: Callable[[str, str, str], Awaitable[PlanResponse]],
) -> None:
    """Legacy adapter: LangGraph SDK thread/run shape.

    Delete once callers move to POST /plans.
    """

    @app.post('/threads', response_model=ThreadResponse)
    async def create_thread() -> ThreadResponse:
        thread_id = uuid.uuid4().hex[:12]
        thread_workspace(thread_id)
        return ThreadResponse(thread_id=thread_id)

    @app.post('/threads/{thread_id}/runs')
    async def run_thread(thread_id: str, request: RunRequest) -> dict:
        messages = request.input.get('messages', [])
        prompt = ''
        for message in reversed(messages):
            if message.get('role') == 'user':
                prompt = message.get('content', '')
                break
        if not prompt:
            raise HTTPException(status_code=400, detail='no user message in input')
        plan = await run_plan_or_503(prompt, user_id='legacy', thread_id=thread_id)
        return {
            'thread_id': thread_id,
            'messages': [
                {
                    'role': 'assistant',
                    'content': plan.strategy.model_dump_json(),
                }
            ],
        }


### [/legacy]
def create_app(
    workspace_root: str | Path = 'workspace',
    database_url: str | None = None,
    orchestrator_model: str | object | None = None,
    researcher_model: str | object | None = None,
    content_writer_model: str | object | None = None,
    step_store=None,
    task_timeout_seconds: float = 600,
) -> FastAPI:
    """Build the FastAPI app.

    database_url selects Postgres persistence; without it, runs use a
    SQLite store under the workspace root. Models are injectable so
    tests can pass TestModel or FunctionModel instances.
    """
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    store = step_store or sqlite_store(root / 'runs.db')
    queues: dict[str, TaskQueue] = {}
    app = FastAPI(title='gtm-agent')

    # Configure before instrumenting: instrument_fastapi() only sends
    # spans once configure() has run. configure_observability() is
    # idempotent, so repeated create_app() calls are safe.
    configure_observability()
    import logfire

    logfire.instrument_fastapi(app)

    def thread_workspace(thread_id: str) -> Path:
        path = root / 'threads' / thread_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thread_queue(thread_id: str) -> TaskQueue:
        if thread_id not in queues:
            queues[thread_id] = TaskQueue(
                thread_workspace(thread_id),
                model=content_writer_model,
                timeout_seconds=task_timeout_seconds,
            )
        return queues[thread_id]

    async def run_plan_or_503(
        prompt: str, user_id: str, thread_id: str
    ) -> PlanResponse:
        """Run a plan, mapping a missing model key to 503."""
        try:
            return await _run_plan(
                store,
                thread_workspace(thread_id),
                thread_queue(thread_id),
                prompt,
                user_id,
                thread_id,
                orchestrator_model=orchestrator_model,
                researcher_model=researcher_model,
            )
        except UserError as exc:
            raise HTTPException(
                status_code=503, detail=f'model not configured: {exc}'
            ) from exc

    ### [health]
    @app.get('/health')
    async def health() -> dict:
        return {'status': 'ok'}

    ### [/health]
    ### [plans]
    @app.post('/plans', response_model=PlanResponse)
    async def create_plan(request: PlanRequest) -> PlanResponse:
        thread_id = request.thread_id or uuid.uuid4().hex[:12]
        return await run_plan_or_503(request.prompt, request.user_id, thread_id)

    ### [/plans]
    @app.get('/threads/{thread_id}/report')
    async def get_report(thread_id: str) -> dict:
        report = thread_workspace(thread_id) / REPORT_WORKSPACE_PATH
        if not report.is_file():
            raise HTTPException(status_code=404, detail='no report yet')
        return {
            'thread_id': thread_id,
            'path': REPORT_PUBLIC_PATH,
            'content': report.read_text(encoding='utf-8'),
        }

    @app.get('/threads/{thread_id}/tasks')
    async def list_tasks(thread_id: str) -> dict:
        return {
            'thread_id': thread_id,
            'tasks': thread_queue(thread_id).list_tasks(),
        }

    @app.post('/threads/{thread_id}/tasks/{task_id}/cancel')
    async def cancel_task(thread_id: str, task_id: str) -> dict:
        try:
            task = await thread_queue(thread_id).cancel_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='unknown task') from None
        return {'thread_id': thread_id, 'task': task}

    # Legacy adapter: LangGraph SDK thread/run shape. Delete once
    # callers move to POST /plans.
    _register_legacy_routes(app, thread_workspace, run_plan_or_503)

    return app


### [main]
def main() -> None:  # pragma: no cover - exercised by deployment, not tests
    import uvicorn

    configure_observability()
    app = create_app(
        workspace_root=os.environ.get('GTM_WORKSPACE', 'workspace'),
        database_url=os.environ.get('DATABASE_URL'),
    )
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))


if __name__ == '__main__':  # pragma: no cover
    main()
