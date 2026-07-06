"""CLI entrypoint for kicking off a single Researcher run end to end.

Usage:
    uv run python -m agents.researcher "topic here"
    uv run python -m agents.researcher "topic here" --audience-tag UPSC
    uv run python -m agents.researcher "topic here" --run-id my-fixed-id -v

Requires OPENAI_API_KEY, EXA_API_KEY, and DB_* set in the environment (see
.env.example) — this calls real OpenAI, real Exa (via `npx exa-mcp-server`),
and writes to the real database configured by DB_*.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid

from dotenv import load_dotenv

from agents.researcher.models import ResearcherInput
from agents.researcher.researcher import Researcher

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.researcher",
        description="Run the Researcher agent end to end for a single topic and print the resulting ResearchBrief.",
    )
    parser.add_argument("topic", help="The blog topic to research.")
    parser.add_argument("--audience-tag", default=None, help='Optional audience framing, e.g. "UPSC".')
    parser.add_argument("--run-id", default=None, help="Defaults to a freshly generated UUID.")
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

    run_id = args.run_id or str(uuid.uuid4())
    researcher_input = ResearcherInput(run_id=run_id, topic=args.topic, audience_tag=args.audience_tag)

    logger.info("Starting Researcher run %s for topic=%r", run_id, args.topic)

    try:
        researcher = Researcher.from_env()
        brief = asyncio.run(researcher.run(researcher_input))
    except Exception:
        logger.exception("Researcher run %s failed", run_id)
        return 1

    print(json.dumps(brief.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
