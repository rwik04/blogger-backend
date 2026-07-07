"""In-process daily scheduler for autonomous topic generation.

Deliberately not a new dependency (no APScheduler/Celery) — a plain
`asyncio` loop that sleeps until the next occurrence of a configured UTC
hour, then runs one autonomous `TopicGenerator` pass with a wide candidate
net trimmed down to the day's best few. Matches this codebase's existing
"small and explicit, no framework" convention (see the custom graph engine
and migration runner).

Gated behind `TOPIC_CRON_ENABLED` (default off) so it never fires
unexpectedly in local dev — only enabled via env var on the deployed
instance.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from agents.topic_generator.models import TopicGeneratorInput, TopicGeneratorMode
from agents.topic_generator.topic_generator import TopicGenerator

logger = logging.getLogger(__name__)

_DEFAULT_CRON_HOUR_UTC = 3
_DEFAULT_CRON_COUNT = 18
"""Wide net across all 11 UPSC subjects — trimmed down to `_DEFAULT_CRON_MAX_OUTPUT`
by relevance_score before persistence."""
_DEFAULT_CRON_MAX_OUTPUT = 5


def _seconds_until_next_run(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


async def run_daily_topic_cron(topic_generator: TopicGenerator) -> None:
    """Runs forever until cancelled — sleeps until the configured UTC hour,
    runs one autonomous batch, logs the outcome, and loops. A failed run is
    logged and swallowed so it doesn't take down the scheduling loop or the
    API process; the next day's run still fires on schedule.
    """
    hour_utc = int(os.environ.get("TOPIC_CRON_HOUR_UTC", str(_DEFAULT_CRON_HOUR_UTC)))
    count = int(os.environ.get("TOPIC_CRON_COUNT", str(_DEFAULT_CRON_COUNT)))
    max_output = int(os.environ.get("TOPIC_CRON_MAX_OUTPUT", str(_DEFAULT_CRON_MAX_OUTPUT)))

    logger.info("Daily topic cron scheduled for %02d:00 UTC (count=%d, max_output=%d)", hour_utc, count, max_output)

    while True:
        sleep_seconds = _seconds_until_next_run(hour_utc)
        logger.info("Daily topic cron sleeping %.0fs until next run", sleep_seconds)
        await asyncio.sleep(sleep_seconds)

        batch_id = str(uuid.uuid4())
        try:
            logger.info("Daily topic cron starting (batch_id=%s)", batch_id)
            output = await topic_generator.run(
                TopicGeneratorInput(mode=TopicGeneratorMode.AUTONOMOUS, count=count, max_output=max_output),
                batch_id=batch_id,
            )
            logger.info(
                "Daily topic cron finished (batch_id=%s): %d topic(s) persisted",
                batch_id,
                len(output.candidates),
            )
        except Exception:
            logger.exception("Daily topic cron run failed (batch_id=%s)", batch_id)

        # Sleep past the run's own duration so the next loop iteration's
        # `_seconds_until_next_run` naturally lands on tomorrow, not today.
        await asyncio.sleep(60)


def is_cron_enabled() -> bool:
    return os.environ.get("TOPIC_CRON_ENABLED", "false").strip().lower() in ("1", "true", "yes")
