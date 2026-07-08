from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


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


class PowerShellSapiTTS:
    """Windows SAPI speech synthesis through PowerShell and System.Speech."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or _find_powershell()

    def available(self) -> bool:
        return bool(self.executable)

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


def _find_powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")
