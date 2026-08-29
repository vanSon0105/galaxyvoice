from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Callable, Protocol

from ..common.cache import write_json_atomic
from ..common.paths import unique_project_dir
from ..reliability.service import estimate_audio_bytes, guard_output_space
from ..voice.audio import try_convert_to_mp3
from .models import (
    CLONE_MODE,
    DESIGN_MODE,
    OMNIVOICE_MODES,
    OmniVoiceGenerationOptions,
    OmniVoiceResult,
)
from .profiles import (
    PendingVoiceProfile,
    discard_pending_profile,
    finalize_voice_profile,
    find_voice_profile,
    prepare_voice_profile,
)
from .runtime import normalize_omnivoice_device


ProgressCallback = Callable[[str], None]


class WorkerClient(Protocol):
    def request(
        self,
        command: str,
        payload: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]: ...


def generate_omnivoice_audio(
    options: OmniVoiceGenerationOptions,
    client: WorkerClient,
    progress: ProgressCallback | None = None,
) -> OmniVoiceResult:
    text = options.text.strip()
    if not text:
        raise ValueError("Hãy nhập nội dung cần tạo giọng.")
    if options.mode not in OMNIVOICE_MODES:
        raise ValueError(f"Chế độ OmniVoice không hợp lệ: {options.mode}")

    guard_output_space(
        options.output_dir,
        required_bytes=estimate_audio_bytes(text, output_count=1 + int(options.export_mp3)),
    )

    profiles_dir = options.profiles_dir
    profile_prompt: Path | None = None
    pending_profile: PendingVoiceProfile | None = None

    if options.mode == CLONE_MODE:
        if options.profile_id:
            if profiles_dir is None:
                raise ValueError("Chưa cấu hình thư mục thư viện giọng.")
            profile = find_voice_profile(profiles_dir, options.profile_id)
            if profile is None:
                raise FileNotFoundError(f"Không tìm thấy profile giọng: {options.profile_id}")
            profile_prompt = profile.prompt_path
        elif options.reference_audio is None or not options.reference_audio.is_file():
            raise ValueError("Nhái giọng cần audio mẫu hoặc profile đã lưu.")

        if options.save_profile_name and not options.profile_id:
            if not options.consent_confirmed:
                raise ValueError("Phải xác nhận quyền sử dụng giọng nói trước khi lưu giọng nhái.")
            if profiles_dir is None:
                raise ValueError("Chưa cấu hình thư mục thư viện giọng.")
            pending_profile = prepare_voice_profile(profiles_dir, options.save_profile_name)

    if options.mode == DESIGN_MODE and not options.instruct.strip():
        raise ValueError("Hãy chọn ít nhất một đặc điểm hoặc nhập mô tả giọng.")

    project_dir = unique_project_dir(options.output_dir, options.project_name, "omnivoice")
    wav_path = project_dir / "voice.wav"
    manifest_path = project_dir / "manifest.json"

    payload: dict[str, object] = {
        "mode": options.mode,
        "text": text,
        "output_path": str(wav_path),
        "model_id": options.model_id.strip(),
        "device": normalize_omnivoice_device(options.device),
        "language": options.language.strip() or "auto",
        "ref_audio": str(options.reference_audio) if options.reference_audio else "",
        "ref_text": options.reference_text.strip(),
        "profile_path": str(profile_prompt) if profile_prompt else "",
        "save_profile_path": str(pending_profile.prompt_path) if pending_profile else "",
        "instruct": options.instruct.strip(),
        "num_step": max(4, min(64, int(options.num_step))),
        "guidance_scale": max(0.0, min(4.0, float(options.guidance_scale))),
        "t_shift": max(0.01, min(1.0, float(options.t_shift))),
        "layer_penalty_factor": max(0.0, min(20.0, float(options.layer_penalty_factor))),
        "position_temperature": max(0.0, min(20.0, float(options.position_temperature))),
        "class_temperature": max(0.0, min(5.0, float(options.class_temperature))),
        "speed": max(0.5, min(1.5, float(options.speed))),
        "duration": options.duration if options.duration and options.duration > 0 else None,
        "denoise": bool(options.denoise),
        "normalize_text": bool(options.normalize_text),
        "preprocess_prompt": bool(options.preprocess_prompt),
        "postprocess_output": bool(options.postprocess_output),
        "audio_chunk_duration": max(0.0, min(120.0, float(options.audio_chunk_duration))),
        "audio_chunk_threshold": max(0.0, min(600.0, float(options.audio_chunk_threshold))),
        "pad_duration": max(0.0, min(5.0, float(options.pad_duration))),
        "fade_duration": max(0.0, min(5.0, float(options.fade_duration))),
        "enable_flashinfer": bool(options.enable_flashinfer),
        "flashinfer_cuda_graph": bool(options.flashinfer_cuda_graph),
        "lora_adapter": options.lora_adapter.strip(),
    }

    try:
        client.request("generate", payload, on_progress=progress)
        if not wav_path.is_file():
            raise RuntimeError("OmniVoice worker không tạo file WAV.")

        profile_id = ""
        if pending_profile is not None:
            profile = finalize_voice_profile(
                pending_profile,
                display_name=options.save_profile_name,
                language=options.language,
                reference_audio=options.reference_audio,
                reference_text=options.reference_text,
                source="cloned",
                consent_confirmed=options.consent_confirmed,
                consent_basis=options.consent_basis,
                consent_statement=options.consent_statement,
            )
            profile_id = profile.profile_id
            # Finalized: a later failure must NOT delete the saved profile.
            pending_profile = None

        warnings: list[str] = []
        mp3_path: Path | None = None
        if options.export_mp3:
            candidate = project_dir / "voice.mp3"
            converted, message = try_convert_to_mp3(wav_path, candidate)
            if converted:
                mp3_path = candidate
            else:
                warnings.append(message)

        manifest_options = asdict(options)
        manifest_options["output_dir"] = str(options.output_dir)
        manifest_options["reference_audio"] = (
            str(options.reference_audio) if options.reference_audio else None
        )
        manifest_options["profiles_dir"] = str(options.profiles_dir) if options.profiles_dir else None
        write_json_atomic(
            manifest_path,
            {
                "version": 1,
                "engine": "omnivoice",
                "options": manifest_options,
                "wav_path": str(wav_path),
                "mp3_path": str(mp3_path) if mp3_path else None,
                "profile_id": profile_id,
                "warnings": warnings,
            },
        )
        return OmniVoiceResult(
            project_dir=project_dir,
            wav_path=wav_path,
            mp3_path=mp3_path,
            manifest_path=manifest_path,
            profile_id=profile_id,
            warnings=tuple(warnings),
        )
    except Exception:
        if pending_profile is not None:
            discard_pending_profile(pending_profile)
        raise
