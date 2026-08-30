from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.parity import get_catalogue


EXPECTED_CASE_IDS = (
    "shared.project_portability",
    "studio.short_tts",
    "studio.long_expressive_tts",
    "batch.fifty_items",
    "library.noisy_clone_consent",
    "transcripts.multilingual_video",
    "dubbing.two_speaker",
    "longform.story",
    "longform.audiobook",
    "reliability.interruption",
    "migration.voicestudio_copy",
)


def test_catalogue_is_stable_required_and_immutable() -> None:
    catalogue = get_catalogue()

    assert tuple(case.case_id for case in catalogue.cases) == EXPECTED_CASE_IDS
    assert all(case.required for case in catalogue.cases)
    with pytest.raises(FrozenInstanceError):
        catalogue.version = "changed"


def test_cases_expose_ordered_contracts_and_immutable_thresholds() -> None:
    case = get_catalogue().cases[0]

    assert case.area == "shared"
    assert case.title
    assert isinstance(case.fixture_roles, tuple)
    assert isinstance(case.checks, tuple)
    assert isinstance(case.manual_prompts, tuple)
    assert case.checks
    assert case.manual_prompts
    with pytest.raises(TypeError):
        case.thresholds["duration_absolute_ms"] = 999
