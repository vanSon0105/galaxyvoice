from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..common.ffmpeg import find_ffmpeg


EDGE_ENGINE_CODE = "edge"
SAPI_ENGINE_CODE = "sapi"
EDGE_ENGINE_LABEL = "Edge TTS (Online)"
SAPI_ENGINE_LABEL = "Windows SAPI (Offline)"
DEFAULT_EDGE_VOICE = "vi-VN-HoaiMyNeural"

_ENGINE_LABELS = {
    EDGE_ENGINE_CODE: EDGE_ENGINE_LABEL,
    SAPI_ENGINE_CODE: SAPI_ENGINE_LABEL,
}


@dataclass(frozen=True)
class Voice:
    name: str
    culture: str
    gender: str
    age: str

    @property
    def label(self) -> str:
        details = ", ".join(part for part in [self.culture, self.gender] if part)
        return f"{self.name} ({details})" if details else self.name


class TTSEngine(Protocol):
    code: str
    label: str

    def available(self) -> bool: ...

    def unavailable_reason(self) -> str: ...

    def list_voices(self) -> list[Voice]: ...

    def initial_voices(self) -> list[Voice]: ...

    def preferred_voice_name(self, language_code: str) -> str | None: ...

    def synthesize_to_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> None: ...


class PowerShellSapiTTS:
    """Windows SAPI speech synthesis through PowerShell and System.Speech."""

    code = SAPI_ENGINE_CODE
    label = SAPI_ENGINE_LABEL

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or _find_powershell()

    def available(self) -> bool:
        return bool(self.executable)

    def unavailable_reason(self) -> str:
        if self.executable:
            return ""
        return "PowerShell was not found. Windows SAPI needs Windows PowerShell or PowerShell 7."

    def list_voices(self) -> list[Voice]:
        script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = $synth.GetInstalledVoices() | ForEach-Object {
        $info = $_.VoiceInfo
        [PSCustomObject]@{
            Name = $info.Name
            Culture = $info.Culture.Name
            Gender = $info.Gender.ToString()
            Age = $info.Age.ToString()
        }
    }
    @($voices) | ConvertTo-Json -Depth 3
}
finally {
    $synth.Dispose()
}
"""
        completed = self._run(script, timeout=30)
        payload = completed.stdout.strip()
        if not payload:
            return []

        data = json.loads(payload)
        if isinstance(data, dict):
            data = [data]

        voices: list[Voice] = []
        for item in data:
            voices.append(
                Voice(
                    name=str(item.get("Name", "")),
                    culture=str(item.get("Culture", "")),
                    gender=str(item.get("Gender", "")),
                    age=str(item.get("Age", "")),
                )
            )
        return [voice for voice in voices if voice.name]

    def initial_voices(self) -> list[Voice]:
        return []

    def preferred_voice_name(self, language_code: str) -> str | None:
        return None

    def synthesize_to_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["GALAXY_TTS_TEXT"] = text
        env["GALAXY_TTS_OUTPUT"] = str(output_path)
        env["GALAXY_TTS_VOICE"] = voice_name or ""
        env["GALAXY_TTS_RATE"] = str(max(-10, min(10, int(rate))))
        env["GALAXY_TTS_VOLUME"] = str(max(0, min(100, int(volume))))

        script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voiceName = $env:GALAXY_TTS_VOICE
    if (-not [string]::IsNullOrWhiteSpace($voiceName)) {
        $synth.SelectVoice($voiceName)
    }
    $synth.Rate = [int]$env:GALAXY_TTS_RATE
    $synth.Volume = [int]$env:GALAXY_TTS_VOLUME
    $synth.SetOutputToWaveFile($env:GALAXY_TTS_OUTPUT)
    $synth.Speak($env:GALAXY_TTS_TEXT) | Out-Null
}
finally {
    $synth.Dispose()
}
"""
        self._run(script, env=env, timeout=max(60, len(text) // 8))
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(
                "Windows SAPI did not create a WAV file. Check that Windows speech voices are installed."
            )

    def _run(
        self,
        script: str,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self.executable:
            raise RuntimeError("PowerShell was not found. This TTS engine requires Windows PowerShell or PowerShell 7.")

        script_path: str | None = None
        script_with_encoding = "\n".join(
            [
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
                "$OutputEncoding = [System.Text.Encoding]::UTF8",
                script,
            ]
        )

        try:
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as handle:
                handle.write(script_with_encoding)
                script_path = handle.name

            completed = subprocess.run(
                [self.executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout,
                check=False,
            )
        finally:
            if script_path:
                Path(script_path).unlink(missing_ok=True)

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "PowerShell TTS command failed."
            raise RuntimeError(message)
        return completed


class EdgeTTS:
    """Microsoft Edge's online neural voices, converted to WAV with ffmpeg."""

    code = EDGE_ENGINE_CODE
    label = EDGE_ENGINE_LABEL

    def __init__(self, edge_module: Any | None = None) -> None:
        self._edge_module = edge_module

    def available(self) -> bool:
        return not self.unavailable_reason()

    def unavailable_reason(self) -> str:
        if not find_ffmpeg():
            return "Edge TTS needs ffmpeg. Run install_ffmpeg.ps1 or add ffmpeg to PATH."
        try:
            self._load_module()
        except RuntimeError as error:
            return str(error)
        return ""

    def list_voices(self) -> list[Voice]:
        module = self._load_module()
        try:
            payload = asyncio.run(asyncio.wait_for(module.list_voices(), timeout=15))
        except Exception as error:
            raise RuntimeError(f"Could not load Edge TTS voices. Check the internet connection: {error}") from error

        voices = [
            Voice(
                name=str(item.get("ShortName", "")),
                culture=str(item.get("Locale", "")),
                gender=str(item.get("Gender", "")),
                age="",
            )
            for item in payload
            if item.get("ShortName")
        ]
        preferred = {
            "vi-VN-HoaiMyNeural": 0,
            "vi-VN-NamMinhNeural": 1,
        }
        return sorted(
            voices,
            key=lambda voice: (
                0 if voice.name in preferred else 1,
                preferred.get(voice.name, 99),
                voice.culture,
                voice.name,
            ),
        )

    def initial_voices(self) -> list[Voice]:
        return [
            Voice(name=DEFAULT_EDGE_VOICE, culture="vi-VN", gender="Female", age=""),
            Voice(name="vi-VN-NamMinhNeural", culture="vi-VN", gender="Male", age=""),
        ]

    def preferred_voice_name(self, language_code: str) -> str | None:
        return DEFAULT_EDGE_VOICE if language_code.strip().lower() == "vi" else None

    def synthesize_to_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> None:
        if not text.strip():
            raise ValueError("Cannot synthesize empty text.")
        if not any(char.isalnum() for char in text):
            raise ValueError("Edge TTS text has no speakable letters or numbers.")
        if not find_ffmpeg():
            raise RuntimeError("Edge TTS needs ffmpeg. Run install_ffmpeg.ps1 or add ffmpeg to PATH.")

        module = self._load_module()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
                temp_path = Path(handle.name)

            for attempt in range(2):
                communicate = module.Communicate(
                    text,
                    voice_name or DEFAULT_EDGE_VOICE,
                    rate=_format_percent(max(-10, min(10, int(rate))) * 10),
                    volume=_format_percent(max(0, min(100, int(volume))) - 100),
                )
                try:
                    asyncio.run(asyncio.wait_for(communicate.save(str(temp_path)), timeout=60))
                    break
                except Exception as error:
                    no_audio_error = getattr(getattr(module, "exceptions", None), "NoAudioReceived", None)
                    if attempt == 0 and no_audio_error and isinstance(error, no_audio_error):
                        temp_path.write_bytes(b"")
                        time.sleep(0.35)
                        continue
                    raise
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise RuntimeError("Edge TTS returned no audio. Check the internet connection and try again.")

            _convert_edge_audio_to_wav(temp_path, output_path)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Edge TTS synthesis failed: {error}") from error
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Edge TTS did not create a WAV file.")

    def _load_module(self) -> Any:
        if self._edge_module is not None:
            return self._edge_module
        try:
            self._edge_module = importlib.import_module("edge_tts")
        except ImportError as error:
            raise RuntimeError(
                "edge-tts is not installed. Run: pip install -r requirements-voice.txt"
            ) from error
        return self._edge_module


def tts_engine_codes() -> tuple[str, ...]:
    return tuple(_ENGINE_LABELS)


def tts_engine_labels() -> tuple[str, ...]:
    return tuple(_ENGINE_LABELS.values())


def tts_engine_code(label_or_code: str) -> str:
    normalized = label_or_code.strip().lower()
    if normalized in _ENGINE_LABELS:
        return normalized
    for code, label in _ENGINE_LABELS.items():
        if label.lower() == normalized:
            return code
    return EDGE_ENGINE_CODE


def create_tts_engine(code: str) -> TTSEngine:
    if tts_engine_code(code) == SAPI_ENGINE_CODE:
        return PowerShellSapiTTS()
    return EdgeTTS()


def _format_percent(value: int) -> str:
    return f"{value:+d}%"


def _convert_edge_audio_to_wav(source_path: Path, output_path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found while converting Edge TTS audio.")

    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffmpeg failed to convert Edge TTS audio to WAV."
        raise RuntimeError(message)


def _find_powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")
