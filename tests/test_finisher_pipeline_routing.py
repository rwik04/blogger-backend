import asyncio

from agents.finisher.models import (
    DraftedMediaPlan,
    DraftedMediaPrompt,
    DraftedQuestion,
    DraftedQuestionSet,
    DraftedStatement,
    QuizRelevanceAssessment,
)
from agents.finisher.pipeline import build_finisher_graph


class _StubLLMClient:
    def __init__(self, quiz_should_be_called: bool, quiz_relevant: bool = True):
        self.quiz_should_be_called = quiz_should_be_called
        self.quiz_relevant = quiz_relevant
        self.called_schemas: list[type] = []

    def reason(self, messages, schema, reasoning_effort=None):
        self.called_schemas.append(schema)

        if schema is QuizRelevanceAssessment:
            return QuizRelevanceAssessment(
                quiz_relevant=self.quiz_relevant,
                reason="Specific figures and named entities throughout."
                if self.quiz_relevant
                else "Mostly narrative framing, nothing concrete to test.",
            )

        if schema is DraftedQuestionSet:
            if not self.quiz_should_be_called:
                raise AssertionError("Quiz LLM call happened even though it shouldn't have")
            return DraftedQuestionSet(
                questions=[
                    DraftedQuestion(
                        question_type="statement_based",
                        stem="Consider the following statements:",
                        statements=[
                            DraftedStatement(
                                text="The tournament will feature 48 teams across 12 groups.",
                                is_true=True,
                                claim_id="claim-1",
                            ),
                            DraftedStatement(
                                text="Matches happen only in Mexico.",
                                is_true=False,
                                claim_id="claim-2",
                            ),
                        ],
                        answer_options=[],
                        explanation="Per the claims above.",
                        related_section_id="intro",
                    )
                ]
            )

        if schema is DraftedMediaPlan:
            return DraftedMediaPlan(
                media=[
                    DraftedMediaPrompt(
                        kind="banner", section_id=None, prompt="A wide banner.", alt_text="Banner alt text."
                    )
                ]
            )

        raise AssertionError(f"unexpected schema requested: {schema}")


class _StubFinisherRepository:
    def __init__(self):
        self.saved_output = None

    def save_finisher_output(self, output):
        self.saved_output = output


def _base_state(include_quiz: bool) -> dict:
    return {
        "run_id": "run-1",
        "topic": "FIFA World Cup 2026",
        "audience_tag": "UPSC",
        "include_quiz": include_quiz,
        "quality_flags": [],
        "research_brief": {
            "run_id": "run-1",
            "sub_queries": [],
            "sources": [],
            "claims": [
                {
                    "id": "claim-1",
                    "text": "The tournament will feature 48 teams across 12 groups.",
                    "source_ids": [],
                    "confidence": "high",
                    "contradicted": False,
                },
                {
                    "id": "claim-2",
                    "text": "Matches are scheduled across the United States, Canada, and Mexico.",
                    "source_ids": [],
                    "confidence": "high",
                    "contradicted": False,
                },
            ],
            "report_markdown": "",
        },
        "strategist_output": {
            "run_id": "run-1",
            "seo_plan": {
                "primary_keyword": "FIFA World Cup 2026",
                "secondary_keywords": ["host cities", "48 teams"],
                "meta_title": "FIFA World Cup 2026: Everything You Need to Know",
                "meta_description": "x" * 140,
                "slug": "fifa-world-cup-2026",
            },
            "outline": [
                {
                    "section_id": "intro",
                    "heading": "Introduction",
                    "target_keyword": "48 teams",
                    "grounded": True,
                    "order_index": 0,
                },
                {
                    "section_id": "logistics",
                    "heading": "Logistics",
                    "target_keyword": "host cities",
                    "grounded": True,
                    "order_index": 1,
                },
            ],
            "narrative_angle": "informative",
        },
        "writer_output": {
            "run_id": "run-1",
            "draft_version": 1,
            "sections": [
                {
                    "section_id": "intro",
                    "heading": "Introduction",
                    "body_markdown": "The tournament will feature 48 teams.",
                    "claim_ids": ["claim-1"],
                    "unsupported_gaps": [],
                    "tone_notes": "",
                    "word_count": 60,
                    "retries_used": 0,
                },
                {
                    "section_id": "logistics",
                    "heading": "Logistics",
                    "body_markdown": "Matches are scheduled across host cities.",
                    "claim_ids": ["claim-2"],
                    "unsupported_gaps": [],
                    "tone_notes": "",
                    "word_count": 40,
                    "retries_used": 0,
                },
            ],
            "needs_more_research": [],
        },
    }


def test_include_quiz_false_skips_quiz_llm_call_entirely():
    llm_client = _StubLLMClient(quiz_should_be_called=False)
    repo = _StubFinisherRepository()
    graph = build_finisher_graph(llm_client, repo, reasoning_effort="medium")

    final_state = asyncio.run(graph.arun(_base_state(include_quiz=False)))

    assert QuizRelevanceAssessment not in llm_client.called_schemas
    assert DraftedQuestionSet not in llm_client.called_schemas
    assert DraftedMediaPlan in llm_client.called_schemas
    assert final_state["output"]["questions"] == []
    assert repo.saved_output is not None


def test_include_quiz_true_runs_the_full_quiz_pipeline():
    llm_client = _StubLLMClient(quiz_should_be_called=True, quiz_relevant=True)
    repo = _StubFinisherRepository()
    graph = build_finisher_graph(llm_client, repo, reasoning_effort="medium")

    final_state = asyncio.run(graph.arun(_base_state(include_quiz=True)))

    assert QuizRelevanceAssessment in llm_client.called_schemas
    assert DraftedQuestionSet in llm_client.called_schemas
    assert len(final_state["output"]["questions"]) >= 1
    assert repo.saved_output is not None


def test_quiz_relevant_false_skips_candidate_generation():
    llm_client = _StubLLMClient(quiz_should_be_called=False, quiz_relevant=False)
    repo = _StubFinisherRepository()
    graph = build_finisher_graph(llm_client, repo, reasoning_effort="medium")

    final_state = asyncio.run(graph.arun(_base_state(include_quiz=True)))

    assert QuizRelevanceAssessment in llm_client.called_schemas
    assert DraftedQuestionSet not in llm_client.called_schemas
    assert DraftedMediaPlan in llm_client.called_schemas
    assert final_state["output"]["questions"] == []
    assert any("not relevant" in flag for flag in final_state["output"]["quality_flags"])
    assert repo.saved_output is not None
