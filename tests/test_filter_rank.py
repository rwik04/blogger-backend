from agents.researcher.models import Source
from agents.researcher.nodes.filter_rank import make_filter_rank_node
from agents.researcher.state import RawSearchHit


def _hit(url: str, domain: str, source_id: str) -> RawSearchHit:
    return RawSearchHit(
        source_id=source_id,
        url=url,
        title=f"Title for {url}",
        domain=domain,
        content="x" * 500,
        needs_scrape=False,
    )


async def test_filter_rank_dedupes_within_round_and_against_cumulative_sources():
    node = make_filter_rank_node()

    state = {
        "sources": [
            Source(
                id="existing-1",
                url="https://existing.com/a",
                title="Existing",
                domain="existing.com",
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        ],
        "round_search_results": [
            {
                "sub_query": "q1",
                "hits": [
                    _hit("https://existing.com/a", "existing.com", "dup-of-existing"),
                    _hit("https://new.com/b", "new.com", "new-1"),
                ],
            },
            {
                "sub_query": "q2",
                "hits": [
                    _hit("https://new.com/b", "new.com", "new-1-dup"),  # same URL, different sub-query
                    _hit("https://pinterest.com/c", "pinterest.com", "blocked-1"),
                ],
            },
        ],
    }

    result = await node(state)

    kept_urls = {hit["url"] for hit in result["round_hits"]}
    assert kept_urls == {"https://new.com/b"}
    assert len(result["sources"]) == 2  # existing + the one new source


async def test_filter_rank_upweights_gov_edu_domains_for_upsc_audience():
    node = make_filter_rank_node()

    state = {
        "audience_tag": "UPSC",
        "sources": [],
        "round_search_results": [
            {
                "sub_query": "q1",
                "hits": [
                    _hit("https://blog.example.com/x", "blog.example.com", "blog-1"),
                    _hit("https://data.gov.in/y", "data.gov.in", "gov-1"),
                ],
            }
        ],
    }

    result = await node(state)

    assert result["round_hits"][0]["domain"] == "data.gov.in"
