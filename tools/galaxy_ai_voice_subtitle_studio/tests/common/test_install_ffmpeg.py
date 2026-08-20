from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FfmpegInstallerTests(unittest.TestCase):
    def test_installer_requires_sha256_before_extracting(self) -> None:
        installer = ROOT / "install_ffmpeg.ps1"
        content = installer.read_text(encoding="utf-8")
        self.assertIn("checksums.sha256", content)
        self.assertIn("Get-FileHash", content)
        self.assertLess(content.index("Assert-ArchiveChecksum"), content.index("Expand-Archive"))

    def test_installer_has_valid_powershell_syntax(self) -> None:
        powershell = shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")
        path = str(ROOT / "install_ffmpeg.ps1").replace("'", "''")
        command = f"""
$content = Get-Content -Raw '{path}'
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
