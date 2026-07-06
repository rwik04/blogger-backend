from agents.researcher.nodes.search import _parse_text_entries


def test_parses_exa_plain_text_format_into_entries():
    # This is exa-mcp-server's actual `web_search_exa` output format: plain
    # "Field: value" text per result, entries separated by a `---` line —
    # no JSON, no structuredContent.
    text = (
        "Title: Host Countries and Cities | FIFA World Cup 2026\n"
        "URL: https://www.fifa.com/en/tournaments/mens/worldcup/host-cities\n"
        "Published: N/A\n"
        "Author: N/A\n"
        "Highlights:\n"
        "USA · Atlanta · Boston · Dallas.\n"
        "\n"
        "---\n"
        "\n"
        "Title: FIFA World Cup 2026 | Fixtures\n"
        "URL: https://www.fifa.com/en/tournaments/mens/worldcup/fixtures\n"
        "Published: 2026-03-30T00:00:00.000Z\n"
        "Author: N/A\n"
        "Highlights:\n"
        "Hosting shared between Canada, Mexico and the USA."
    )

    entries = _parse_text_entries(text)

    assert len(entries) == 2
    assert entries[0]["URL"] == "https://www.fifa.com/en/tournaments/mens/worldcup/host-cities"
    assert entries[0]["Title"] == "Host Countries and Cities | FIFA World Cup 2026"
    assert "Atlanta" in entries[0]["Highlights"]
    assert entries[1]["URL"] == "https://www.fifa.com/en/tournaments/mens/worldcup/fixtures"


def test_ignores_entries_without_a_url():
    text = "Title: No URL here\nAuthor: N/A\n"
    assert _parse_text_entries(text) == []


def test_empty_text_yields_no_entries():
    assert _parse_text_entries("") == []
