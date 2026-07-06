"""CLI entrypoint for running the Writer agent against an existing,
already-persisted Strategist run.

Usage:
    uv run python -m agents.writer --run-id <run-id>
    uv run python -m agents.writer --run-id <run-id> -v

Requires OPENAI_API_KEY and DB_* set in the environment (see .env.example),
and a run that already completed `research` and `strategize` for
`--run-id` (i.e. both a persisted `ResearchBrief` and `StrategistOutput`).

No orchestrator chains Strategist -> Writer automatically yet — this is a
deliberately separate, sequential step for now.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from agents.writer.models import WriterInput
from agents.writer.writer import Writer
from db.engine import get_engine
from db.repositories.writer_repository import WriterRepository

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.writer",
        description=(
            "Run the Writer agent against an existing run's persisted ResearchBrief "
            "and StrategistOutput, and print the resulting WriterOutput."
        ),
    )
    parser.add_argument("--run-id", required=True, help="run_id of a completed Researcher + Strategist run.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug-level logging (per-node agent_events + internals)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    repo = WriterRepository(get_engine())
    try:
        run = repo.get_run(args.run_id)
        research_brief = repo.load_research_brief(args.run_id)
        strategist_output = repo.load_strategist_output(args.run_id)
    except Exception:
        logger.exception("Failed to load run context for run_id=%s", args.run_id)
        return 1

    writer_input = WriterInput(
        run_id=args.run_id,
        topic=run["topic"],
        audience_tag=run.get("audience_tag"),
        research_brief=research_brief,
        strategist_output=strategist_output,
    )

    logger.info("Starting Writer run %s for topic=%r", args.run_id, run["topic"])

    try:
        writer = Writer.from_env()
        output = asyncio.run(writer.run(writer_input))
    except Exception:
        logger.exception("Writer run %s failed", args.run_id)
        return 1

    print(json.dumps(output.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
