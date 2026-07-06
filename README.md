# blogger-backend

Presswork CMS backend. First of a handful of hosted services that will coordinate
with each other; this repo currently holds the `llm` module (client + adapter
pattern) and the `db` module (pooled Postgres engine + programmatic table
creation), with the rest of the service (API layer) to follow.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
# fill in OPENAI_API_KEY and DB_* (AWS RDS Postgres) in .env
```

## Structure

```
src/
  llm/
    client.py            LLMClient + create_adapter() factory
    adapters/
      base.py            BaseLLMAdapter (ABC): complete(), reason()
      openai.py          OpenAIAdapter — the only provider implemented so far
  db/
    settings.py          DatabaseSettings.from_env() — reads DB_* env vars
    engine.py             get_engine() — pooled, lazily-built SQLAlchemy engine; ping()
    schema.py             shared MetaData + create_tables()/table_exists() helpers
```

`llm`, `db`, and future top-level modules under `src/`, are flat packages (no
package-name subfolder), matching the shape of `meridian/worker/`.

## Usage

```python
from llm.client import LLMClient

client = LLMClient(provider="openai", api_key="...", model="gpt-4o-mini")

text = client.complete([{"role": "user", "content": "Say hi"}])

from pydantic import BaseModel

class Greeting(BaseModel):
    message: str

greeting = client.reason(
    [{"role": "user", "content": "Return a JSON greeting"}],
    Greeting,
)
```

## Database

Connects to AWS RDS Postgres via a pooled SQLAlchemy engine, configured from
discrete `DB_*` env vars (see `.env.example`). No concrete table schemas are
defined yet — `create_tables()` is generic and works against any `Table`
objects registered on `db.schema.metadata` elsewhere in the codebase:

```python
from sqlalchemy import Column, String, Table
from db.engine import get_engine, ping
from db.schema import metadata, create_tables, table_exists

blogs = Table(
    "blogs", metadata,
    Column("id", String, primary_key=True),
    Column("title", String, nullable=False),
)

ping()                        # health check, returns bool
create_tables(get_engine())   # creates `blogs` if missing, no-op otherwise
table_exists(get_engine(), "blogs")  # True
```

## Development

```bash
uv run pytest
```
