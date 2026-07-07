"""CLI entrypoint for the Topic Generator agent — the pre-Researcher stage
that proposes and classifies UPSC-relevant topic candidates.

Usage:
    uv run python -m agents.topic_generator --mode autonomous
    uv run python -m agents.topic_generator --mode directed --instruction "Recent Supreme Court rulings" --count 5
    uv run python -m agents.topic_generator --mode autonomous --auto-approve -v

Requires OPENAI_API_KEY, EXA_API_KEY, and DB_* set in the environment (see
.env.example). No orchestrator chains Topic Generator -> Researcher
automatically — selecting a candidate topic (`POST /topics/{id}/select`, or
a future CLI flag) is a deliberately separate step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from agents.topic_generator.models import TopicGeneratorInput, TopicGeneratorMode
from agents.topic_generator.topic_generator import TopicGenerator

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m agents.topic_generator",
        description="Run the Topic Generator agent and print the resulting candidate list.",
    )
    parser.add_argument("--mode", required=True, choices=["autonomous", "directed"])
    parser.add_argument(
        "--instruction", default=None, help="Steering instruction, required when --mode directed."
    )
    parser.add_argument("--count", type=int, default=8, help="Target number of candidates (default: 8).")
    parser.add_argument(
        "--max-output",
        type=int,
        default=None,
        help="If set, keep only the top N candidates by relevance_score after classification.",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-mark the top surviving candidate as selected.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug-level logging (per-node batch events + internals)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        generator_input = TopicGeneratorInput(
            mode=TopicGeneratorMode(args.mode),
            user_instruction=args.instruction,
            count=args.count,
            auto_approve=args.auto_approve,
            max_output=args.max_output,
        )
    except Exception:
        logger.exception("Invalid input")
        return 1

    logger.info("Starting Topic Generator run mode=%s count=%d", args.mode, args.count)

    try:
        generator = TopicGenerator.from_env()
        output = asyncio.run(generator.run(generator_input))
    except Exception:
        logger.exception("Topic Generator run failed")
        return 1

    print(json.dumps(output.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
