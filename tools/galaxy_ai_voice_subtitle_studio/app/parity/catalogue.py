"""Fixed native parity validation catalogue."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .models import ParityCase, ParityCatalogue, ThresholdValue


CATALOGUE_VERSION = "2026-08-30"

_DEFAULT_THRESHOLDS: Mapping[str, ThresholdValue] = MappingProxyType(
    {
        "duration_absolute_ms": 250,
        "duration_relative_ratio": 0.05,
        "narration_loudness_target_lufs": -16.0,
        "loudness_tolerance_lu": 2.0,
        "reference_performance_ratio": 1.25,
        "interaction_p95_ms": 200,
        "cpu_cancellation_seconds": 2.0,
        "accelerator_cancellation_seconds": 5.0,
    }
)


def _case(
    case_id: str,
    area: str,
    title: str,
    fixture_roles: tuple[str, ...],
    checks: tuple[str, ...],
    manual_prompts: tuple[str, ...],
) -> ParityCase:
    return ParityCase(
        case_id=case_id,
        area=area,
        title=title,
        required=True,
        fixture_roles=fixture_roles,
        checks=checks,
        manual_prompts=manual_prompts,
        thresholds=_DEFAULT_THRESHOLDS,
    )


_CATALOGUE = ParityCatalogue(
    version=CATALOGUE_VERSION,
    cases=(
        _case(
            "shared.project_portability",
            "shared",
            "Project portability and handoff",
            ("portable_project",),
            (
                "project_reopen",
                "moved_directory_portability",
                "missing_media_relink",
                "handoff_return",
            ),
            ("Confirm the reopened and moved project retains its intended content.",),
        ),
        _case(
            "studio.short_tts",
            "studio",
            "Short single-speaker TTS",
            ("short_tts", "short_tts_reference"),
            ("output_format", "duration", "identity_mapping", "loudness"),
            ("Confirm the native take is intelligible and free of obvious artifacts.",),
        ),
        _case(
            "studio.long_expressive_tts",
            "studio",
            "Long expressive TTS",
            ("long_tts", "long_tts_reference"),
            ("output_format", "duration", "terminology", "loudness"),
            ("Confirm expression and terminology remain appropriate throughout.",),
        ),
        _case(
            "batch.fifty_items",
            "batch",
            "Fifty-item deterministic batch",
            ("batch_manifest", "batch_reference"),
            ("item_outcomes", "output_format", "deterministic_failures"),
            ("Confirm successful items are usable and failures are actionable.",),
        ),
        _case(
            "library.noisy_clone_consent",
            "library",
            "Noisy clone reference and consent",
            ("noisy_clone_audio", "clone_consent_variants"),
            ("consent_gate", "identity_mapping", "output_format"),
            ("Confirm the accepted clone preserves identity without unsafe consent.",),
        ),
        _case(
            "transcripts.multilingual_video",
            "transcripts",
            "Multilingual timed video transcript",
            ("multilingual_video", "timed_captions"),
            ("subtitle_order", "subtitle_timing", "language_mapping"),
            ("Confirm captions remain readable and synchronized across languages.",),
        ),
        _case(
            "dubbing.two_speaker",
            "dubbing",
            "Two-speaker dubbing project",
            ("dubbing_project", "mixed_source_audio"),
            ("speaker_mapping", "subtitle_timing", "output_streams"),
            ("Confirm speaker identity and dialogue timing remain natural.",),
        ),
        _case(
            "longform.story",
            "longform",
            "Multi-character story",
            ("story_script", "story_reference"),
            ("character_mapping", "chapter_order", "checkpoint_resume"),
            ("Confirm character voices and narrative continuity remain coherent.",),
        ),
        _case(
            "longform.audiobook",
            "longform",
            "EPUB and PDF audiobook",
            ("epub_source", "pdf_source", "audiobook_reference"),
            ("chapter_boundaries", "chapter_order", "checkpoint_resume"),
            ("Confirm chapter structure and narration are suitable for listening.",),
        ),
        _case(
            "reliability.interruption",
            "reliability",
            "Cancellation and interrupted recovery",
            ("resumable_workflow",),
            (
                "cancellation_acknowledgement",
                "task_reconciliation",
                "recovery_route",
                "interaction_responsiveness",
            ),
            ("Confirm cancellation and recovery guidance are clear and trustworthy.",),
        ),
        _case(
            "migration.voicestudio_copy",
            "migration",
            "VoiceStudio copied-data rehearsal",
            ("voicestudio_copy", "persona_bundle"),
            (
                "source_immutability",
                "consent_mapping",
                "missing_media",
                "sandbox_cleanup",
            ),
            ("Confirm migration warnings and relink actions support a safe decision.",),
        ),
    ),
)


def get_catalogue() -> ParityCatalogue:
    return _CATALOGUE
