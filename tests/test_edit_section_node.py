import pytest

from agents.researcher.models import Claim, ResearchBrief
from agents.strategist.models import OutlineSection, StrategistOutput, SeoPlan
from agents.writer.models import DraftedSection, EditPreset, EditSectionInput
from agents.writer.nodes.edit_section import edit_section
from db.repositories.errors import SectionNotFoundError, WriterOutputNotFoundError

_LONG_BODY = " ".join(["word"] * 60)

_OUTLINE = [
    OutlineSection(section_id="intro", heading="Intro", target_keyword="kw1", grounded=True, order_index=0),
    OutlineSection(section_id="body", heading="Body", target_keyword="kw2", grounded=True, order_index=1),
]

_CLAIMS = [
    Claim(id="claim-1", text="The sky is blue.", source_ids=["s1"], confidence="high", contradicted=False),
    Claim(id="claim-2", text="Water boils at 100C.", source_ids=["s2"], confidence="high", contradicted=False),
]

_CURRENT_SECTIONS = [
    {
        "section_id": "intro",
        "heading": "Intro",
        "body_markdown": "Old intro text.",
        "claim_ids": ["claim-1"],
        "unsupported_gaps": [],
        "tone_notes": "",
        "word_count": 3,
        "retries_used": 0,
    },
    {
        "section_id": "body",
        "heading": "Body",
        "body_markdown": "Old body text.",
        "claim_ids": ["claim-2"],
        "unsupported_gaps": [],
        "tone_notes": "",
        "word_count": 3,
        "retries_used": 0,
    },
]


def _research_brief() -> ResearchBrief:
    return ResearchBrief(run_id="run-1", sub_queries=[], sources=[], claims=_CLAIMS)


def _strategist_output() -> StrategistOutput:
    return StrategistOutput(
        run_id="run-1",
        seo_plan=SeoPlan(
            primary_keyword="kw1",
            secondary_keywords=[],
            meta_title="title",
            meta_description="desc",
            slug="slug",
        ),
        outline=_OUTLINE,
        narrative_angle="angle",
    )


def _edit_input(section_id="intro", preset=EditPreset.MORE_ENGAGING, instruction=None) -> EditSectionInput:
    return EditSectionInput(
        run_id="run-1",
        topic="Test Topic",
        audience_tag=None,
        research_brief=_research_brief(),
        strategist_output=_strategist_output(),
        section_id=section_id,
        preset=preset,
        instruction=instruction,
    )


class _StubLLMClient:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict], type, str | None]] = []

    def reason(self, messages, schema, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _StubWriterRepo:
    def __init__(self, latest_draft):
        self._latest_draft = latest_draft
        self.saved_output: dict | None = None

    def load_latest_draft(self, run_id):
        return self._latest_draft

    def get_next_draft_version(self, run_id):
        current_version = self._latest_draft["version"] if self._latest_draft else 0
        return current_version + 1

    def save_writer_output(self, output):
        self.saved_output = output


def _section(body_markdown, claim_ids, unsupported_gaps, tone_notes="polished") -> DraftedSection:
    return DraftedSection(
        body_markdown=body_markdown, claim_ids=claim_ids, unsupported_gaps=unsupported_gaps, tone_notes=tone_notes
    )


def _draft(version=1, sections=None):
    return {"draft_id": "draft-1", "version": version, "created_by_agent": "writer", "sections": sections or list(_CURRENT_SECTIONS)}


async def test_preset_maps_to_fixed_instruction_and_replaces_only_target_section():
    stub_llm = _StubLLMClient([_section(_LONG_BODY, ["claim-1"], [])])
    repo = _StubWriterRepo(_draft())

    output = await edit_section(stub_llm, repo, _edit_input(section_id="intro"), reasoning_effort="low")

    assert len(stub_llm.calls) == 1
    prompt = stub_llm.calls[0][0][1]["content"]
    assert "engaging" in prompt.lower()

    assert len(output.sections) == 2
    edited = next(s for s in output.sections if s.section_id == "intro")
    unedited = next(s for s in output.sections if s.section_id == "body")
    assert edited.body_markdown == _LONG_BODY
    assert unedited.body_markdown == "Old body text."  # untouched
    assert output.draft_version == 2  # bumped from the existing draft's version 1
    assert repo.saved_output is not None
    assert repo.saved_output["draft_version"] == 2


async def test_custom_preset_uses_caller_supplied_instruction():
    stub_llm = _StubLLMClient([_section(_LONG_BODY, ["claim-1"], [])])
    repo = _StubWriterRepo(_draft())

    await edit_section(
        stub_llm,
        repo,
        _edit_input(section_id="intro", preset=EditPreset.CUSTOM, instruction="Make it about penguins."),
        reasoning_effort="low",
    )

    prompt = stub_llm.calls[0][0][1]["content"]
    assert "Make it about penguins." in prompt


async def test_custom_preset_without_instruction_is_rejected_at_the_model_level():
    with pytest.raises(ValueError):
        _edit_input(section_id="intro", preset=EditPreset.CUSTOM, instruction=None)


async def test_missing_draft_raises_writer_output_not_found():
    stub_llm = _StubLLMClient([])
    repo = _StubWriterRepo(None)

    with pytest.raises(WriterOutputNotFoundError):
        await edit_section(stub_llm, repo, _edit_input(), reasoning_effort="low")


async def test_unknown_section_id_raises_section_not_found():
    stub_llm = _StubLLMClient([])
    repo = _StubWriterRepo(_draft())

    with pytest.raises(SectionNotFoundError):
        await edit_section(stub_llm, repo, _edit_input(section_id="nope"), reasoning_effort="low")


async def test_edit_reuses_gap_retry_loop():
    responses = [
        _section(_LONG_BODY, ["claim-1"], ["gap A"]),
        _section(_LONG_BODY, ["claim-1"], []),
    ]
    stub_llm = _StubLLMClient(responses)
    repo = _StubWriterRepo(_draft())

    output = await edit_section(stub_llm, repo, _edit_input(section_id="intro"), reasoning_effort="low")

    assert len(stub_llm.calls) == 2
    edited = next(s for s in output.sections if s.section_id == "intro")
    assert edited.retries_used == 1
    assert edited.unsupported_gaps == []
