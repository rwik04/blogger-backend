"""Non-agent-specific database resource queries: run listings/counts for a
dashboard/health-check view, and the fully-assembled "publish-ready blog"
join used by `GET /runs/{run_id}/blog`. Doesn't extend `BaseAgentRepository`
since none of its `agent_events`/`agent_steps` emission machinery applies
here — this repository only reads.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, func, literal, select, union_all

from db.tables import (
    blog_drafts,
    blog_runs,
    blog_section_claims,
    blog_sections,
    media_assets,
    published_blogs,
    quiz_questions,
    seo_audits,
)

_COUNTED_TABLES = {
    "blog_drafts": blog_drafts,
    "blog_sections": blog_sections,
    "seo_audits": seo_audits,
    "quiz_questions": quiz_questions,
    "media_assets": media_assets,
}


class ResourcesRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def count_runs_by_status(self) -> dict[str, int]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(blog_runs.c.status, func.count().label("count")).group_by(blog_runs.c.status)
            ).all()
        return {status: count for status, count in rows}

    def list_runs(self, limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict[str, Any]]:
        query = select(
            blog_runs.c.id.label("run_id"),
            blog_runs.c.topic,
            blog_runs.c.audience_tag,
            blog_runs.c.status,
            blog_runs.c.paused,
            blog_runs.c.created_at,
        ).order_by(blog_runs.c.created_at.desc())
        if status is not None:
            query = query.where(blog_runs.c.status == status)
        query = query.limit(limit).offset(offset)

        with self._engine.begin() as conn:
            rows = conn.execute(query).mappings().all()
        return [dict(row) for row in rows]

    def count_resources(self) -> dict[str, int]:
        """One round trip instead of seven: each table's count used to be its
        own separate query in the same connection, and against a high-latency
        remote DB that's ~7x the round-trip cost for what's fundamentally one
        logical "give me all the dashboard counts" read. `UNION ALL` folds
        every count into a single statement/round trip.
        """
        selects = [
            select(literal(name).label("name"), func.count().label("count")).select_from(table)
            for name, table in _COUNTED_TABLES.items()
        ]
        selects.append(
            select(
                literal("published_blogs_staged").label("name"),
                func.count().label("count"),
            ).select_from(published_blogs).where(published_blogs.c.published_at.is_(None))
        )
        selects.append(
            select(
                literal("published_blogs_published").label("name"),
                func.count().label("count"),
            ).select_from(published_blogs).where(published_blogs.c.published_at.is_not(None))
        )

        with self._engine.begin() as conn:
            rows = conn.execute(union_all(*selects)).all()
        return {name: count for name, count in rows}

    def get_full_blog(self, run_id: str) -> dict[str, Any] | None:
        """The fully assembled, publish-ready blog for `run_id`: staged
        `published_blogs` metadata + the latest draft's ordered sections +
        quiz questions + media prompts + the SEO audit. Returns `None` if
        Finisher hasn't completed for this run yet (no `published_blogs`
        row), which the API maps to 404.
        """
        with self._engine.begin() as conn:
            blog_row = (
                conn.execute(select(published_blogs).where(published_blogs.c.run_id == run_id))
                .mappings()
                .first()
            )
            if blog_row is None:
                return None

            draft_row = (
                conn.execute(
                    select(blog_drafts.c.id, blog_drafts.c.version)
                    .where(blog_drafts.c.run_id == run_id)
                    .order_by(blog_drafts.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )

            sections: list[dict[str, Any]] = []
            if draft_row is not None:
                section_rows = (
                    conn.execute(
                        select(blog_sections)
                        .where(blog_sections.c.draft_id == draft_row["id"])
                        .order_by(blog_sections.c.order_index.asc())
                    )
                    .mappings()
                    .all()
                )
                section_ids = [row["id"] for row in section_rows]
                # One query for every section's claim_ids instead of one
                # query per section (N+1) — grouped back out in Python.
                claims_by_section: dict[Any, list[Any]] = {sid: [] for sid in section_ids}
                if section_ids:
                    claim_rows = conn.execute(
                        select(blog_section_claims.c.section_id, blog_section_claims.c.claim_id).where(
                            blog_section_claims.c.section_id.in_(section_ids)
                        )
                    ).all()
                    for section_id, claim_id in claim_rows:
                        claims_by_section[section_id].append(claim_id)

                for section_row in section_rows:
                    section = dict(section_row)
                    section["claim_ids"] = claims_by_section[section_row["id"]]
                    sections.append(section)

            questions = [
                dict(row)
                for row in conn.execute(
                    select(quiz_questions).where(quiz_questions.c.run_id == run_id)
                )
                .mappings()
                .all()
            ]
            media = [
                dict(row)
                for row in conn.execute(select(media_assets).where(media_assets.c.run_id == run_id))
                .mappings()
                .all()
            ]
            audit_row = (
                conn.execute(
                    select(seo_audits)
                    .where(seo_audits.c.run_id == run_id)
                    .order_by(seo_audits.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )

        return {
            "run_id": run_id,
            "final_title": blog_row["final_title"],
            "final_tags": blog_row["tags"],
            "subject": blog_row["subject"],
            "published_at": blog_row["published_at"],
            "canonical_url": blog_row["canonical_url"],
            "draft_version": draft_row["version"] if draft_row is not None else None,
            "sections": sections,
            "questions": questions,
            "media": media,
            "seo_audit": dict(audit_row) if audit_row is not None else None,
        }
