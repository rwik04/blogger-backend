import itertools

from agents.finisher.models import UpscStyleQuestion
from agents.finisher.nodes.assemble_questions import (
    _THREE_STATEMENT_OPTIONS,
    _TWO_STATEMENT_OPTIONS,
    assemble_question,
    select_questions,
)


def _candidate(pattern, section_id="sec-1"):
    statements = [
        {"text": f"Statement {i + 1}", "is_true": is_true, "claim_id": f"claim-{i + 1}"}
        for i, is_true in enumerate(pattern)
    ]
    return {
        "stem": "Consider the following statements:",
        "statements": statements,
        "explanation": "Because of the claims.",
        "related_section_id": section_id,
    }


def test_all_two_statement_patterns_resolve_to_the_right_option():
    for pattern, expected_text in _TWO_STATEMENT_OPTIONS.items():
        question = assemble_question(_candidate(pattern))
        assert question is not None
        correct = next(o for o in question.options if o.label == question.correct_option)
        assert correct.text == expected_text


def test_valid_three_statement_patterns_resolve_to_the_right_option():
    for pattern, expected_text in _THREE_STATEMENT_OPTIONS.items():
        question = assemble_question(_candidate(pattern))
        assert question is not None
        correct = next(o for o in question.options if o.label == question.correct_option)
        assert correct.text == expected_text


def test_three_statement_patterns_with_fewer_than_two_true_are_rejected():
    invalid_patterns = [p for p in itertools.product([True, False], repeat=3) if sum(p) < 2]
    assert len(invalid_patterns) == 4  # (F,F,F), (T,F,F), (F,T,F), (F,F,T)
    for pattern in invalid_patterns:
        assert assemble_question(_candidate(pattern)) is None


def test_distractors_are_always_the_other_three_never_the_correct_option():
    for pattern in _TWO_STATEMENT_OPTIONS:
        question = assemble_question(_candidate(pattern))
        correct = next(o for o in question.options if o.label == question.correct_option)
        distractor_texts = [o.text for o in question.options if o.label != question.correct_option]
        assert correct.text not in distractor_texts
        assert len(set(distractor_texts)) == 3

    for pattern in _THREE_STATEMENT_OPTIONS:
        question = assemble_question(_candidate(pattern))
        correct = next(o for o in question.options if o.label == question.correct_option)
        distractor_texts = [o.text for o in question.options if o.label != question.correct_option]
        assert correct.text not in distractor_texts
        assert len(set(distractor_texts)) == 3


def _question(question_id: str, section_id: str) -> UpscStyleQuestion:
    return UpscStyleQuestion(
        question_id=question_id,
        stem="stem",
        statements=[],
        options=[],
        correct_option="a",
        explanation="",
        related_section_id=section_id,
    )


def test_select_questions_prefers_distinct_sections_then_tops_up():
    questions = [
        _question("q0", "sec-1"),
        _question("q1", "sec-1"),
        _question("q2", "sec-2"),
        _question("q3", "sec-1"),
    ]

    selected = select_questions(questions, target_count=3)

    assert len(selected) == 3
    assert {q.question_id for q in selected} == {"q0", "q1", "q2"}
    # One question per distinct section chosen first (q0, q2), then topped
    # up from the remaining pool (q1) even though sec-1 repeats.
    section_ids = [q.related_section_id for q in selected]
    assert section_ids.count("sec-2") == 1


def test_select_questions_caps_at_target_count():
    questions = [_question(f"q{i}", f"sec-{i}") for i in range(6)]
    selected = select_questions(questions, target_count=4)
    assert len(selected) == 4
