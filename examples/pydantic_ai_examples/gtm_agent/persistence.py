"""StepPersistence wiring: SQLite locally, Postgres in deployment.

StepPersistence records message history only. It does not restore
capability state or replay anything by itself. Resume by passing a
snapshot's messages back as message_history.

Postgres: the caller owns the asyncpg pool lifecycle. Build the store
with postgres_store, keep the pool, and close it on shutdown.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

from pydantic_ai.messages import ModelMessage
from pydantic_ai_harness.step_persistence import (
    PostgresStepStore,
    SqliteStepStore,
    StepStore,
    continue_run,
    fork_run,
)


### [stores]
def sqlite_store(database: str | Path) -> SqliteStepStore:
    """A SQLite step store at the given path."""
    return SqliteStepStore(database=database)


async def postgres_store(
    database_url: str, table: str = 'step_persistence'
) -> tuple[PostgresStepStore, asyncpg.Pool]:
    """A Postgres step store. Returns the store and its pool.

    Close the pool on shutdown: await pool.close().
    """
    pool = await asyncpg.create_pool(database_url)
    return PostgresStepStore(pool, table=table), pool


### [/stores]
### [resume]
async def unresolved_effects(store: StepStore, run_id: str) -> list:
    """Tool effects that started but have no terminal record.

    A started effect with no terminal record may or may not have
    happened. Check this before resuming from an interrupted snapshot.
    """
    return await store.list_unresolved_tool_effects(run_id=run_id)


async def resume_history(store: StepStore, run_id: str) -> list[ModelMessage]:
    """Messages to resume a run from its latest settled snapshot.

    Resumes from an interrupted snapshot only when no tool effect is
    unresolved. Resuming from an interrupted point re-runs its open
    calls, so take that point only when nothing is in doubt.
    """
    unresolved = await unresolved_effects(store, run_id)
    return await continue_run(store, run_id=run_id, include_interrupted=not unresolved)


async def fork_history(store: StepStore, run_id: str) -> list[ModelMessage]:
    """Messages to fork a run. Start the fork under a new conversation."""
    return await fork_run(store, run_id=run_id)


### [/resume]
