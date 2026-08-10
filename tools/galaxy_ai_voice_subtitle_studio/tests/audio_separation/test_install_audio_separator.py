from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class AudioSeparatorInstallerTests(unittest.TestCase):
    def test_installer_is_valid_and_pins_the_reviewed_runtime(self) -> None:
        powershell = shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable.")

        installer = ROOT / "install_audio_separator.ps1"
        content = installer.read_text(encoding="utf-8")
        self.assertIn('$runtimeVersion = "0.44.5"', content)
        self.assertIn('"audio-separator[$extra]==$runtimeVersion"', content)
        self.assertIn("GalaxyAIStudio\\models\\AudioSeparator", content)

        installer_literal = str(installer).replace("'", "''")
        command = f"""
$content = Get-Content -Raw '{installer_literal}'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $content,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count) {{ $errors | Out-String | Write-Error; exit 2 }}
"""
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
