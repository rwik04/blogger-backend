"""CLI entrypoint for running the Strategist agent against an existing,
already-persisted Researcher run.

Usage:
    uv run python -m agents.strategist --run-id <run-id>
    uv run python -m agents.strategist --run-id <run-id> --audience-tag UPSC
    uv run python -m agents.strategist --run-id <run-id> -v

Requires OPENAI_API_KEY and DB_* set in the environment (see .env.example),
and a Researcher run that already completed and persisted a `ResearchBrief`
for `--run-id` (i.e. `uv run research "<topic>" --run-id <run-id>` first).

No orchestrator chains Researcher -> Strategist automatically yet — this is
a deliberately separate, sequential step for now.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from agents.strategist.models import StrategistInput
from agents.strategist.strategist import Strategist
from db.engine import get_engine
from db.repositories.strategist_repository import StrategistRepository

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.strategist",
        description=(
            "Run the Strategist agent against an existing Researcher run's persisted "
            "ResearchBrief, and print the resulting StrategistOutput."
        ),
    )
    parser.add_argument("--run-id", required=True, help="run_id of a completed Researcher run.")
    parser.add_argument(
        "--audience-tag",
        default=None,
        help='Override the audience tag stored on blog_runs (e.g. "UPSC").',
    )
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

    repo = StrategistRepository(get_engine())
    try:
        run = repo.get_run(args.run_id)
        research_brief = repo.load_research_brief(args.run_id)
    except Exception:
        logger.exception("Failed to load run context for run_id=%s", args.run_id)
        return 1

    audience_tag = args.audience_tag or run.get("audience_tag")
    strategist_input = StrategistInput(
        run_id=args.run_id,
        topic=run["topic"],
        audience_tag=audience_tag,
        research_brief=research_brief,
    )

    logger.info("Starting Strategist run %s for topic=%r", args.run_id, run["topic"])

    try:
        strategist = Strategist.from_env()
        output = asyncio.run(strategist.run(strategist_input))
    except Exception:
        logger.exception("Strategist run %s failed", args.run_id)
        return 1

    print(json.dumps(output.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
