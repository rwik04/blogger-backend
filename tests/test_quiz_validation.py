from agents.finisher.nodes.validate_questions import validate_candidate

_CLAIMS_BY_ID = {
    "claim-1": "The tournament will feature 48 teams across 12 groups.",
    "claim-2": "Matches are scheduled across the United States, Canada, and Mexico.",
}


def _statement(text: str, is_true: bool, claim_id: str) -> dict:
    return {"text": text, "is_true": is_true, "claim_id": claim_id}


def _candidate(*statements: dict) -> dict:
    return {"statements": list(statements)}


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
