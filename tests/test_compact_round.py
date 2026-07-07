from agents.researcher.models import Claim, ExtractedClaim
from agents.researcher.nodes.compact_round import _merge_claims


def test_merge_claims_appends_new_distinct_claim():
    existing = [Claim(id="claim-1", text="The sky is blue.", source_ids=["s1"], confidence="medium", contradicted=False)]
    new = [ExtractedClaim(text="Water boils at 100C at sea level.", source_ids=["s2"], confidence="high", contradicted=False)]

    merged = _merge_claims(existing, new)

    assert len(merged) == 2
    assert {c.text for c in merged} == {"The sky is blue.", "Water boils at 100C at sea level."}


def test_merge_claims_combines_repeated_claim_and_upgrades_confidence():
    existing = [Claim(id="claim-1", text="The sky is blue.", source_ids=["s1"], confidence="medium", contradicted=False)]
    new = [ExtractedClaim(text="the sky is blue.  ", source_ids=["s2"], confidence="low", contradicted=False)]

    merged = _merge_claims(existing, new)

    assert len(merged) == 1
    assert sorted(merged[0].source_ids) == ["s1", "s2"]
    assert merged[0].confidence == "high"


def test_merge_claims_preserves_contradicted_flag():
    existing = [Claim(id="claim-1", text="X causes Y.", source_ids=["s1"], confidence="medium", contradicted=True)]
    new = [ExtractedClaim(text="X causes Y.", source_ids=["s2"], confidence="medium", contradicted=False)]

    merged = _merge_claims(existing, new)

    assert merged[0].contradicted is True


def test_merge_claims_dedupes_source_ids_within_a_brand_new_claim():
    # The LLM occasionally cites the same source twice for one claim — this
    # must not reach research_claim_sources (keyed on claim_id/source_id) as
    # a duplicate pair.
    new = [ExtractedClaim(text="The sky is blue.", source_ids=["s1", "s1", "s2"], confidence="high", contradicted=False)]

    merged = _merge_claims([], new)

    assert merged[0].source_ids == ["s1", "s2"]


def test_merge_claims_dedupes_source_ids_across_a_merge():
    existing = [Claim(id="claim-1", text="The sky is blue.", source_ids=["s1"], confidence="medium", contradicted=False)]
    new = [ExtractedClaim(text="the sky is blue.", source_ids=["s1", "s2"], confidence="low", contradicted=False)]

    merged = _merge_claims(existing, new)

    assert merged[0].source_ids == ["s1", "s2"]
