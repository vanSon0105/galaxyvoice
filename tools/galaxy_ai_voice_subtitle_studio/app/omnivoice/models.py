from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


AUTO_MODE = "auto"
CLONE_MODE = "clone"
DESIGN_MODE = "design"
OMNIVOICE_MODES = (AUTO_MODE, CLONE_MODE, DESIGN_MODE)
DEFAULT_MODEL_ID = "k2-fsa/OmniVoice"


@dataclass(frozen=True)
class OmniVoiceGenerationOptions:
    mode: str
    text: str
    output_dir: Path
    project_name: str = "omnivoice"
    model_id: str = DEFAULT_MODEL_ID
    device: str = "auto"
    language: str = "vi"
    reference_audio: Path | None = None
    reference_text: str = ""
    profile_id: str = ""
    save_profile_name: str = ""
    profiles_dir: Path | None = None
    instruct: str = ""
    num_step: int = 32
    guidance_scale: float = 2.0
    t_shift: float = 0.1
    layer_penalty_factor: float = 5.0
    position_temperature: float = 5.0
    class_temperature: float = 0.0
    speed: float = 1.0
    duration: float | None = None
    denoise: bool = True
    normalize_text: bool = False
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    audio_chunk_duration: float = 15.0
    audio_chunk_threshold: float = 30.0
    pad_duration: float = 0.0
    fade_duration: float = 0.02
    export_mp3: bool = False


@dataclass(frozen=True)
class OmniVoiceResult:
    project_dir: Path
    wav_path: Path
    mp3_path: Path | None
    manifest_path: Path
    profile_id: str = ""
    warnings: tuple[str, ...] = ()
