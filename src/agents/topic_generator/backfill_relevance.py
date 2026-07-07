"""One-off CLI: scores every `topics` row persisted before `relevance_score`
existed (i.e. `relevance_score IS NULL`), one LLM call per topic, grounded in
the same fields the `classify` step already produced (title, summary,
subject, why_this_topic, current_relevance). Safe to re-run — only rows still
missing a score are touched, and each one is persisted individually so a
crash partway through doesn't lose earlier progress.

Usage:
    uv run backfill-topic-relevance
    uv run backfill-topic-relevance -v
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from agents.prompts.topic_generator import BACKFILL_RELEVANCE_SYSTEM, build_backfill_relevance_user_prompt
from agents.topic_generator.models import RelevanceScoreOnly
from db.engine import get_engine
from db.repositories.topic_repository import TopicRepository
from llm.client import LLMClient

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backfill-topic-relevance",
        description="Score every topic missing a relevance_score, one LLM call at a time.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging.")
    return parser.parse_args(argv)


async def _backfill(llm_client: LLMClient, repo: TopicRepository) -> tuple[int, int]:
    topics = await asyncio.to_thread(repo.list_topics_missing_relevance_score)
    scored = 0
    failed = 0

    for topic in topics:
        title = topic["title"]
        try:
            messages = [
                {"role": "system", "content": BACKFILL_RELEVANCE_SYSTEM},
                {"role": "user", "content": build_backfill_relevance_user_prompt(topic)},
            ]
            result: RelevanceScoreOnly = await asyncio.to_thread(llm_client.reason, messages, RelevanceScoreOnly)
            await asyncio.to_thread(repo.update_relevance_score, topic["id"], result.relevance_score)
            scored += 1
            logger.info("Scored %r -> %d (%d/%d)", title, result.relevance_score, scored + failed, len(topics))
        except Exception:
            failed += 1
            logger.exception("Failed to score topic id=%s title=%r", topic["id"], title)

    return scored, failed


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    llm_client = LLMClient(
        provider="openai",
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    repo = TopicRepository(get_engine())

    scored, failed = asyncio.run(_backfill(llm_client, repo))
    logger.info("Backfill complete: %d scored, %d failed", scored, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
