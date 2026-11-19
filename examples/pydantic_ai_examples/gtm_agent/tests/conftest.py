from __future__ import annotations

import pytest


@pytest.fixture(scope='session')
def anyio_backend() -> str:
    """The GTM example is asyncio-only: the task queue leans on `asyncio.create_task`, so `--anyio-backend=trio` does not apply here."""
    return 'asyncio'
