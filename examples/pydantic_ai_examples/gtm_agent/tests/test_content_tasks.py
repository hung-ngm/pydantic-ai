"""Async content task tests: state machine and orchestrator tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_examples.gtm_agent.agents import (
    build_orchestrator_agent,
    build_researcher_agent,
)
from pydantic_ai_examples.gtm_agent.models import (
    REPORT_PUBLIC_PATH,
    ContentBrief,
    GtmDeps,
)
from pydantic_ai_examples.gtm_agent.tasks import TaskQueue

from .test_parity import STRATEGY_FIELDS, scripted_researcher_model

BRIEF = ContentBrief(
    kind='blog',
    audience='AI platform teams',
    key_messages=['Ship agents in production'],
    tone='clear, direct, confident',
    source_report_path=REPORT_PUBLIC_PATH,
)

BLOG_MD = '# Ship agents in production\n\nOur SDK helps teams ship agents.'


def writer_model(behavior: str = 'ok') -> FunctionModel:
    """Script the content writer: save the file, then return the path.

    The task id comes from the prompt, so the same model works for
    tasks created inside an orchestrator run.
    """
    import re

    calls = {'n': 0}

    def task_id_from(messages: list) -> str:
        for message in messages:
            for part in getattr(message, 'parts', []):
                content = getattr(part, 'content', '')
                if isinstance(content, str):
                    match = re.search(r'Task id: (\w+)', content)
                    if match:
                        return match.group(1)
        return 'unknown'

    async def fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if behavior == 'error':
            raise RuntimeError('writer failed')
        if behavior == 'slow':
            await asyncio.sleep(3600)
        task_id = task_id_from(messages)
        if calls['n'] == 1:
            return ModelResponse(
                parts=[ToolCallPart('save_content', {'content': BLOG_MD})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    'final_result',
                    {
                        'task_id': task_id,
                        'deliverable_path': f'content/{task_id}.md',
                        'summary': 'A blog post about shipping agents.',
                    },
                )
            ]
        )

    return FunctionModel(fn)


async def test_task_succeeds_and_writes_file(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path, model=writer_model())
    task = queue.create_task(BRIEF)
    queue.start_task(task.id)
    done = await queue.wait_for(task.id)
    assert done.status == 'success'
    assert done.deliverable_path == f'content/{task.id}.md'
    path = tmp_path / 'content' / f'{task.id}.md'
    assert path.is_file()
    assert path.read_text(encoding='utf-8') == BLOG_MD


async def test_task_error_marks_status(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path)
    task = queue.create_task(BRIEF)
    queue.model = writer_model(behavior='error')
    queue.start_task(task.id)
    done = await queue.wait_for(task.id)
    assert done.status == 'error'
    assert done.deliverable_path is None


async def test_task_timeout_marks_status(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path, timeout_seconds=0.05)
    task = queue.create_task(BRIEF)
    queue.model = writer_model(behavior='slow')
    queue.start_task(task.id)
    done = await queue.wait_for(task.id)
    assert done.status == 'timeout'


async def test_task_cancel_marks_status(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path)
    task = queue.create_task(BRIEF)
    queue.model = writer_model(behavior='slow')
    queue.start_task(task.id)
    await asyncio.sleep(0.05)
    cancelled = await queue.cancel_task(task.id)
    assert cancelled.status == 'cancelled'


async def test_orchestrator_starts_content_task(tmp_path: Path) -> None:
    queue = TaskQueue(tmp_path, model=writer_model())
    calls = {'n': 0}

    async def orchestrator_fn(messages: list, info: AgentInfo) -> ModelResponse:
        calls['n'] += 1
        if calls['n'] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart('start_content_task', {'brief': BRIEF.model_dump()})
                ]
            )
        return ModelResponse(
            parts=[ToolCallPart('final_result', dict(STRATEGY_FIELDS))]
        )

    orchestrator = build_orchestrator_agent(
        tmp_path,
        researcher=build_researcher_agent(tmp_path, model=scripted_researcher_model()),
        model=FunctionModel(orchestrator_fn),
        task_queue=queue,
    )
    result = await orchestrator.run('Build a GTM plan', deps=GtmDeps(user_id='test'))
    assert result.output.positioning
    tasks = queue.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    done = await queue.wait_for(task.id)
    assert done.status == 'success'
    assert (tmp_path / 'content' / f'{task.id}.md').is_file()
