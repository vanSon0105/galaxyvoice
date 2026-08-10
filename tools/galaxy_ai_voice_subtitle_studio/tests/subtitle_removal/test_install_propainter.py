from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class ProPainterInstallerTests(unittest.TestCase):
    def test_python_probe_tolerates_missing_launcher_versions(self) -> None:
        powershell = shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable.")

        installer = ROOT / "install_propainter.ps1"
        installer_literal = str(installer).replace("'", "''")
        command = f"""
$content = Get-Content -Raw '{installer_literal}'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $content,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count) {{ exit 2 }}
$functionAst = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Find-CompatiblePython'
}}, $true)
Invoke-Expression $functionAst.Extent.Text
$ErrorActionPreference = 'Stop'
Find-CompatiblePython | Out-Null
"""
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
