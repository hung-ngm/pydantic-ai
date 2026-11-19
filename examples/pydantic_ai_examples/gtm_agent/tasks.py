"""Async content task queue.

The application owns the queue. Content creation is a background
worker, not model-controlled delegation, so it lives here instead of
in a Harness capability: the orchestrator only enqueues briefs, and
this queue runs the content-writer agent for each one.

A task is a ContentTask state machine. The queue transitions it:
pending -> running -> success | error | timeout | cancelled.
Cancellation goes through asyncio task cancellation; a task the user
stopped stays cancelled until it is started again.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from pydantic_ai import Agent

from .agents import build_content_writer_agent
from .models import ContentBrief, ContentTask, GtmDeps


### [queue]
class TaskQueue:
    """In-memory queue of content-writer runs for one workspace."""

    def __init__(
        self,
        workspace: str | Path,
        model: str | object | None = None,
        timeout_seconds: float = 600,
    ) -> None:
        self.workspace = workspace
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._tasks: dict[str, ContentTask] = {}
        self._handles: dict[str, asyncio.Task] = {}
        self._users: dict[str, str] = {}

    def create_task(self, brief: ContentBrief, user_id: str = 'system') -> ContentTask:
        """Record a brief as a pending task and return it."""
        task = ContentTask(id=uuid.uuid4().hex[:12], brief=brief, status='pending')
        self._tasks[task.id] = task
        self._users[task.id] = user_id
        return task

    def start_task(self, task_id: str) -> ContentTask:
        """Start a pending task in the background. Must run in a loop."""
        task = self._get(task_id)
        task.status = 'running'
        handle = asyncio.get_running_loop().create_task(self._run(task))
        self._handles[task_id] = handle
        return task

    async def cancel_task(self, task_id: str) -> ContentTask:
        """Cancel a running task. A stopped task stays cancelled."""
        task = self._get(task_id)
        handle = self._handles.get(task_id)
        if handle is not None and not handle.done():
            handle.cancel()
            try:
                await handle
            except asyncio.CancelledError:
                pass
        task.status = 'cancelled'
        return task

    def get_task(self, task_id: str) -> ContentTask:
        """Return one task by id, raising KeyError when unknown."""
        return self._get(task_id)

    def list_tasks(self) -> list[ContentTask]:
        """Return all tasks in creation order."""
        return list(self._tasks.values())

    async def wait_for(self, task_id: str) -> ContentTask:
        """Wait until a task settles and return it."""
        handle = self._handles.get(task_id)
        if handle is not None:
            try:
                await handle
            except asyncio.CancelledError:
                pass
        return self._get(task_id)

    def _get(self, task_id: str) -> ContentTask:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise KeyError(f'unknown content task: {task_id}') from None

    async def _run(self, task: ContentTask) -> ContentTask:
        writer: Agent[GtmDeps, object] = build_content_writer_agent(
            self.workspace, task.id, task.brief, model=self.model
        )
        prompt = (
            f'Task id: {task.id}. '
            f'Write the {task.brief.kind} for {task.brief.audience}. '
            f'Key messages: {"; ".join(task.brief.key_messages)}. '
            f'Tone: {task.brief.tone}.'
        )
        try:
            result = await asyncio.wait_for(
                writer.run(
                    prompt,
                    deps=GtmDeps(user_id=self._users.get(task.id, 'system')),
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            task.status = 'timeout'
            return task
        except asyncio.CancelledError:
            task.status = 'cancelled'
            raise
        except Exception:
            task.status = 'error'
            return task
        task.deliverable_path = result.output.deliverable_path
        task.status = 'success'
        return task


### [/queue]
