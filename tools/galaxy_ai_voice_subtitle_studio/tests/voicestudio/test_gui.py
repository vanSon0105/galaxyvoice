from __future__ import annotations

import unittest
from pathlib import Path

from app.voicestudio.gui import VoiceStudioTabMixin
from app.voicestudio.runtime import VoiceStudioRuntimeStatus


def ready_status() -> VoiceStudioRuntimeStatus:
    return VoiceStudioRuntimeStatus(
        snapshot_present=True,
        runtime_installed=True,
        webview_installed=True,
        backend_online=False,
        update_required=False,
        version="0.4.2",
        license_id="AGPL-3.0-only",
        python_path=Path("runtime/python.exe"),
        source_dir=Path("runtime/sources/0.4.2"),
        missing_components=(),
        message="VoiceStudio đã sẵn sàng",
    )


class VoiceStudioAutoStartHarness(VoiceStudioTabMixin):
    def __init__(self) -> None:
        self.voicestudio_webview = None
        self._voicestudio_launching = False
        self._voicestudio_installing = False
        self._voicestudio_user_stopped = False
        self._voicestudio_auto_launch_attempted = False
        self._voicestudio_launch_failed = False
        self.launches: list[tuple[VoiceStudioRuntimeStatus | None, bool]] = []

    def _voicestudio_tab_is_active(self) -> bool:
        return True

    def _launch_voicestudio(
        self,
        *,
        status: VoiceStudioRuntimeStatus | None = None,
        automatic: bool = False,
    ) -> None:
        self.launches.append((status, automatic))


class VoiceStudioAutoStartTests(unittest.TestCase):
    def test_opening_the_tab_auto_starts_once(self) -> None:
        harness = VoiceStudioAutoStartHarness()
        status = ready_status()

        harness._activate_voicestudio_tab(status)
        harness._activate_voicestudio_tab(status)

        self.assertEqual(harness.launches, [(status, True)])
        self.assertTrue(harness._voicestudio_auto_launch_attempted)

    def test_failed_or_user_stopped_runtime_waits_for_retry(self) -> None:
        status = ready_status()
        for state in ("failed", "stopped"):
            with self.subTest(state=state):
                harness = VoiceStudioAutoStartHarness()
                harness._voicestudio_auto_launch_attempted = True
                harness._voicestudio_launch_failed = state == "failed"
                harness._voicestudio_user_stopped = state == "stopped"

                harness._activate_voicestudio_tab(status)

                self.assertEqual(harness.launches, [])


if __name__ == "__main__":
    unittest.main()
