"""CLI entrypoint for running the Finisher agent against an existing,
already-persisted Writer run.

Usage:
    uv run python -m agents.finisher --run-id <run-id>
    uv run python -m agents.finisher --run-id <run-id> --no-quiz
    uv run python -m agents.finisher --run-id <run-id> --quiz -v

Requires OPENAI_API_KEY and DB_* set in the environment (see .env.example),
and a Writer run that already completed and persisted a `WriterOutput` for
`--run-id` (i.e. `uv run write --run-id <run-id>` first).

Quiz generation defaults to `FINISHER_GENERATE_QUIZ` (default: on) and can
be overridden per run with `--quiz`/`--no-quiz`.

No orchestrator chains Writer -> Finisher automatically yet — this is a
deliberately separate, sequential step for now.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

from agents.finisher.finisher import Finisher
from agents.finisher.models import FinisherInput
from db.engine import get_engine
from db.repositories.finisher_repository import FinisherRepository

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.finisher",
        description=(
            "Run the Finisher agent against an existing Writer run's persisted "
            "WriterOutput, and print the resulting FinisherOutput."
        ),
    )
    parser.add_argument("--run-id", required=True, help="run_id of a completed Writer run.")
    parser.add_argument(
        "--audience-tag",
        default=None,
        help='Override the audience tag stored on blog_runs (e.g. "UPSC").',
    )
    quiz_group = parser.add_mutually_exclusive_group()
    quiz_group.add_argument(
        "--quiz",
        dest="quiz",
        action="store_true",
        default=None,
        help="Force quiz generation on for this run (overrides FINISHER_GENERATE_QUIZ).",
    )
    quiz_group.add_argument(
        "--no-quiz",
        dest="quiz",
        action="store_false",
        help="Skip quiz generation for this run (overrides FINISHER_GENERATE_QUIZ).",
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

    repo = FinisherRepository(get_engine())
    try:
        run = repo.get_run(args.run_id)
        research_brief = repo.load_research_brief(args.run_id)
        strategist_output = repo.load_strategist_output(args.run_id)
        writer_output = repo.load_writer_output(args.run_id)
    except Exception:
        logger.exception("Failed to load run context for run_id=%s", args.run_id)
        return 1

    audience_tag = args.audience_tag or run.get("audience_tag")
    include_quiz = args.quiz if args.quiz is not None else _env_bool("FINISHER_GENERATE_QUIZ", True)

    finisher_input = FinisherInput(
        run_id=args.run_id,
        topic=run["topic"],
        audience_tag=audience_tag,
        include_quiz=include_quiz,
        research_brief=research_brief,
        strategist_output=strategist_output,
        writer_output=writer_output,
    )

    logger.info(
        "Starting Finisher run %s for topic=%r (include_quiz=%s)", args.run_id, run["topic"], include_quiz
    )

    try:
        finisher = Finisher.from_env()
        output = asyncio.run(finisher.run(finisher_input))
    except Exception:
        logger.exception("Finisher run %s failed", args.run_id)
        return 1

    print(json.dumps(output.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
