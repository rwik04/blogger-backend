"""Every repository in `db/repositories/` is synchronous (`psycopg2`, not an
async driver), but every route handler is `async def`. Calling a repository
method directly — as every router did until this was introduced — runs that
blocking network round-trip to RDS *on the event loop itself*, serializing
every single request the process handles (regardless of DB connection pool
size) for the full duration of each query. Under any concurrent load (e.g. a
frontend polling several endpoints every few seconds) this makes the whole
API feel "extremely slow" even though any individual query is fast.

`run_sync` offloads one blocking call to the default thread pool executor,
same pattern already used for the agent pipeline's background jobs (see
`agents/writer/nodes/persist.py`'s `asyncio.to_thread(repo.save_writer_output, ...)`)
— just applied consistently to every request-path repository call too.
"""

from __future__ import annotations

import asyncio
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    return await asyncio.to_thread(fn, *args, **kwargs)
