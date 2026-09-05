"""Lazy adapters for Galaxy-owned runtimes and model catalogs."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .capabilities import (
    CapabilityDescriptor,
    CapabilityRegistry,
    FunctionCapabilityAdapter,
    PreflightRequest,
    PreflightResult,
)
from .models import FunctionModelAdapter, ModelDescriptor, ModelRegistry


def _simple_result(
    request: PreflightRequest,
    *,
    ready: bool,
    message: str,
    resolved_device: str = "",
) -> PreflightResult:
    if ready:
        return PreflightResult.ready(
            request.capability_id,
            requested_device=request.device,
            resolved_device=resolved_device,
            message=message,
        )
    return PreflightResult.unavailable(
        request.capability_id,
        requested_device=request.device,
        resolved_device=resolved_device,
        message=message,
    )


def _tts_preflight(engine_code: str, request: PreflightRequest) -> PreflightResult:
    from ..voice.tts import create_tts_engine

    engine = create_tts_engine(engine_code)
    available = engine.available()
    return _simple_result(
        request,
        ready=available,
        message="TTS runtime is ready." if available else engine.unavailable_reason(),
        resolved_device="remote" if engine_code == "edge" else "cpu",
    )


def _omnivoice_preflight(request: PreflightRequest) -> PreflightResult:
    from ..omnivoice.runtime import OmniVoiceRuntime, inspect_runtime, inspect_runtime_devices

    status = inspect_runtime(OmniVoiceRuntime.default())
    if not status.installed:
        return _simple_result(request, ready=False, message=status.message)
    devices = inspect_runtime_devices(OmniVoiceRuntime.default())
    fallback_device = next(
        (item for item in ("cuda", "xpu", "cpu") if item in devices),
        "cpu",
    )
    device = fallback_device if request.device == "auto" else request.device
    if request.device != "auto" and device not in devices:
        return _simple_result(
            request,
            ready=False,
            message=(
                f"OmniVoice runtime không dùng được {device.upper()}. "
                f"Thiết bị hiện có: {', '.join(devices).upper()}."
            ),
            resolved_device=fallback_device,
        )
    return _simple_result(
        request,
        ready=True,
        message=status.message,
        resolved_device=device,
    )


def _whisper_preflight(request: PreflightRequest) -> PreflightResult:
    if importlib.util.find_spec("faster_whisper") is None:
        return _simple_result(
            request,
            ready=False,
            message="faster-whisper is not installed.",
        )
    from ..common.compute import resolve_whisper_runtime

    device, compute_type = resolve_whisper_runtime(request.device)
    return _simple_result(
        request,
        ready=True,
        message=f"faster-whisper is ready ({compute_type}).",
        resolved_device=device,
    )


def _diarization_preflight(request: PreflightRequest) -> PreflightResult:
    try:
        installed = importlib.util.find_spec("pyannote.audio") is not None
    except ModuleNotFoundError:
        installed = False
    if not installed:
        return _simple_result(
            request,
            ready=False,
            message="pyannote.audio is not installed.",
        )
    token = next(
        (
            os.environ.get(name, "").strip()
            for name in ("GALAXY_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")
            if os.environ.get(name, "").strip()
        ),
        "",
    )
    available_devices = set(_available_diarization_devices())
    resolved_device = (
        "cuda" if request.device == "auto" and "cuda" in available_devices
        else "cpu" if request.device == "auto"
        else request.device
    )
    device_ready = resolved_device in available_devices
    return _simple_result(
        request,
        ready=bool(token) and device_ready,
        message=(
            f"Speaker diarization is ready on {resolved_device.upper()}."
            if token and device_ready
            else f"Speaker diarization cannot use {resolved_device.upper()} on this machine."
            if token
            else "A Hugging Face token is required for speaker diarization."
        ),
        resolved_device=resolved_device,
    )


def _available_diarization_devices() -> tuple[str, ...]:
    devices = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            devices.insert(0, "cuda")
    except Exception:
        pass
    return tuple(devices)


def _translation_preflight(provider_code: str, request: PreflightRequest) -> PreflightResult:
    from ..voice.translator import default_translation_api_key

    is_local = provider_code == "ollama"
    has_credentials = is_local or bool(default_translation_api_key(provider_code))
    return _simple_result(
        request,
        ready=has_credentials,
        message=(
            f"{provider_code} translation is configured."
            if has_credentials
            else f"API key is missing for {provider_code}."
        ),
        resolved_device="local" if is_local else "remote",
    )


def _audio_separation_preflight(request: PreflightRequest) -> PreflightResult:
    from ..audio_separation.service import audio_separator_runtime_ready, resolve_audio_device

    method = request.options.get("method", "mdx")
    try:
        resolved_device = resolve_audio_device(request.device, method)
    except RuntimeError as error:
        return _simple_result(
            request,
            ready=False,
            message=str(error),
            resolved_device="cpu",
        )
    ready, message = audio_separator_runtime_ready(
        processing_device=resolved_device,
        method=method,
    )
    if not ready and request.device == "auto" and resolved_device != "cpu":
        cpu_ready, cpu_message = audio_separator_runtime_ready(
            processing_device="cpu",
            method=method,
        )
        if cpu_ready:
            ready = True
            resolved_device = "cpu"
            message = f"{message} Falling back to CPU. {cpu_message}"
    return _simple_result(
        request,
        ready=ready,
        message=message,
        resolved_device=resolved_device,
    )


def _ffmpeg_preflight(request: PreflightRequest) -> PreflightResult:
    from ..common.ffmpeg import find_ffmpeg

    path = find_ffmpeg()
    return _simple_result(
        request,
        ready=bool(path),
        message=f"FFmpeg is ready: {path}" if path else "FFmpeg was not found.",
        resolved_device="cpu",
    )


def create_default_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    definitions = (
        (
            CapabilityDescriptor(
                "tts.edge", "tts", "Edge TTS", "edge-tts", ("remote",), "remote"
            ),
            lambda request: _tts_preflight("edge", request),
        ),
        (
            CapabilityDescriptor(
                "tts.sapi", "tts", "Windows SAPI", "windows-sapi", ("cpu",), "cpu"
            ),
            lambda request: _tts_preflight("sapi", request),
        ),
        (
            CapabilityDescriptor(
                "tts.omnivoice",
                "tts",
                "OmniVoice",
                "omnivoice-local",
                ("auto", "cuda", "xpu", "cpu"),
                installable=True,
            ),
            _omnivoice_preflight,
        ),
        (
            CapabilityDescriptor(
                "asr.faster-whisper",
                "asr",
                "Faster Whisper",
                "faster-whisper",
                ("auto", "cuda", "cpu"),
                resumable=True,
                installable=True,
            ),
            _whisper_preflight,
        ),
        (
            CapabilityDescriptor(
                "diarization.pyannote",
                "diarization",
                "Pyannote speaker diarization",
                "pyannote-audio",
                ("auto", "cuda", "cpu"),
                installable=True,
            ),
            _diarization_preflight,
        ),
        (
            CapabilityDescriptor(
                "audio.separation",
                "audio",
                "Audio Separator",
                "audio-separator",
                ("auto", "cuda", "directml", "cpu"),
                installable=True,
            ),
            _audio_separation_preflight,
        ),
        (
            CapabilityDescriptor(
                "media.ffmpeg", "media", "FFmpeg", "ffmpeg", ("cpu",), "cpu"
            ),
            _ffmpeg_preflight,
        ),
    )
    for descriptor, preflight in definitions:
        registry.register(FunctionCapabilityAdapter(descriptor, preflight))

    from ..voice.translator import TRANSLATION_PROVIDERS

    for code, provider in TRANSLATION_PROVIDERS.items():
        descriptor = CapabilityDescriptor(
            capability_id=f"translation.{code}",
            kind="translation",
            label=provider.label,
            runtime_id=code,
            devices=("local",) if code == "ollama" else ("remote",),
            default_device="local" if code == "ollama" else "remote",
        )
        registry.register(
            FunctionCapabilityAdapter(
                descriptor,
                lambda request, provider_code=code: _translation_preflight(
                    provider_code, request
                ),
            )
        )
    return registry


def _audio_models(refresh: bool) -> tuple[ModelDescriptor, ...]:
    from ..audio_separation.service import (
        discover_uvr_models,
        list_downloadable_audio_models,
    )

    del refresh
    installed = {model.filename.casefold() for model in discover_uvr_models()}
    return tuple(
        ModelDescriptor(
            model_id=model.filename,
            capability_id="audio.separation",
            label=model.name,
            installed=model.filename.casefold() in installed,
            source="audio-separator",
        )
        for model in list_downloadable_audio_models()
    )


def _install_audio_model(model_id: str, context: object) -> ModelDescriptor:
    from ..audio_separation.service import download_audio_model, list_downloadable_audio_models

    model = next(
        (item for item in list_downloadable_audio_models() if item.filename == model_id),
        None,
    )
    if model is None:
        raise KeyError(f"Unknown audio separation model: {model_id}")
    report = getattr(context, "report", None)
    stop_event = getattr(context, "stop_event", None)
    download_audio_model(
        model,
        progress=(lambda message: report(message)) if callable(report) else None,
        stop_event=stop_event,
        task_id=getattr(context, "task_id", None),
    )
    return ModelDescriptor(
        model_id=model.filename,
        capability_id="audio.separation",
        label=model.name,
        installed=True,
        source="audio-separator",
    )


def create_default_model_registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        FunctionModelAdapter(
            "audio.separation",
            list_models=_audio_models,
            install_model=_install_audio_model,
        )
    )
    return registry


capability_registry = create_default_capability_registry()
model_registry = create_default_model_registry()
