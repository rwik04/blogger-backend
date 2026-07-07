from agents.finisher.nodes.validate_questions import validate_candidate

_CLAIMS_BY_ID = {
    "claim-1": "The tournament will feature 48 teams across 12 groups.",
    "claim-2": "Matches are scheduled across the United States, Canada, and Mexico.",
}


def _statement(text: str, is_true: bool, claim_id: str) -> dict:
    return {"text": text, "is_true": is_true, "claim_id": claim_id}


def _candidate(*statements: dict) -> dict:
    return {"question_type": "statement_based", "statements": list(statements)}


def _answer_option(text: str, is_correct: bool, claim_id: str | None) -> dict:
    return {"text": text, "is_correct": is_correct, "claim_id": claim_id}


def _direct_candidate(*options: dict) -> dict:
    return {"question_type": "direct", "answer_options": list(options)}


def test_valid_two_statement_candidate_passes():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
        _statement("Matches happen only in Mexico.", False, "claim-2"),
    )
    assert validate_candidate(candidate, _CLAIMS_BY_ID) is None


def test_unknown_claim_id_fails():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams.", True, "claim-999"),
        _statement("Matches happen only in Mexico.", False, "claim-2"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "unknown claim_id" in reason


def test_true_statement_with_low_overlap_to_its_claim_fails():
    candidate = _candidate(
        _statement("The tournament will be held on the moon.", True, "claim-1"),
        _statement("Matches happen only in Mexico.", False, "claim-2"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "tagged true" in reason


def test_false_statement_near_verbatim_of_its_claim_fails():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
        _statement("The tournament will feature 48 teams across 12 groups.", False, "claim-1"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "mistagged" in reason


def test_false_statement_unrelated_to_any_claim_fails():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
        _statement("Bananas are an excellent source of potassium.", False, "claim-2"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "unrelated" in reason


def test_near_duplicate_statements_within_one_candidate_fail():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "near-duplicates" in reason


def test_three_statement_with_fewer_than_two_true_fails():
    candidate = _candidate(
        _statement("The tournament will feature 48 teams across 12 groups.", True, "claim-1"),
        _statement("Matches happen only in Mexico.", False, "claim-2"),
        _statement("Matches will be scheduled only across Mexico.", False, "claim-2"),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "true statement" in reason


def test_wrong_statement_count_fails():
    candidate = _candidate(_statement("Only one statement here.", True, "claim-1"))
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "statement(s)" in reason


def test_valid_direct_candidate_passes():
    candidate = _direct_candidate(
        _answer_option("48", True, "claim-1"),
        _answer_option("32", False, None),
        _answer_option("64", False, None),
    )
    assert validate_candidate(candidate, _CLAIMS_BY_ID) is None


def test_direct_candidate_with_no_correct_option_fails():
    candidate = _direct_candidate(
        _answer_option("48", False, "claim-1"),
        _answer_option("32", False, None),
        _answer_option("64", False, None),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "tagged correct" in reason


def test_direct_candidate_with_two_correct_options_fails():
    candidate = _direct_candidate(
        _answer_option("48", True, "claim-1"),
        _answer_option("48 teams total", True, "claim-1"),
        _answer_option("64", False, None),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "tagged correct" in reason


def test_direct_candidate_correct_option_ungrounded_fails():
    candidate = _direct_candidate(
        _answer_option("100", True, "claim-1"),
        _answer_option("32", False, None),
        _answer_option("64", False, None),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "doesn't closely match" in reason


def test_direct_candidate_with_too_few_options_fails():
    candidate = _direct_candidate(
        _answer_option("48", True, "claim-1"),
        _answer_option("32", False, None),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "answer option(s)" in reason


def test_direct_candidate_with_duplicate_options_fails():
    candidate = _direct_candidate(
        _answer_option("48", True, "claim-1"),
        _answer_option("48", False, None),
        _answer_option("64", False, None),
    )
    reason = validate_candidate(candidate, _CLAIMS_BY_ID)
    assert reason is not None
    assert "near-duplicates" in reason
