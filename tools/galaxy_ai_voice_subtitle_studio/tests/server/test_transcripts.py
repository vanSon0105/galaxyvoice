from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app.server.main import create_app
from app.server.routers import transcripts as transcript_router
from app.transcripts.models import TranscriptCue, TranscriptProject, TranscriptWord
from app.transcripts.repository import RevisionConflictError, TranscriptRepository
from app.transcripts.service import SpeakerTurn, TranscriptService


class TranscriptApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_transcripts_test_")
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        self.client = TestClient(create_app(config_path=self.config_path))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_import_text_srt_creates_project_and_lists(self) -> None:
        srt_content = (
            "1\n00:00:01,000 --> 00:00:04,000\nXin chào các bạn\n\n"
            "2\n00:00:04,500 --> 00:00:07,000\nChào mừng tới Galaxy Studio\n"
        )
        response = self.client.post(
            "/api/transcripts/import-text",
            json={
                "project_id": "proj-1",
                "name": "Bài giới thiệu",
                "content": srt_content,
                "format_type": "srt",
                "language": "vi",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["name"], "Bài giới thiệu")
        self.assertEqual(data["cue_count"], 2)
        self.assertEqual(len(data["cues"]), 2)
        self.assertEqual(data["cues"][0]["text"], "Xin chào các bạn")
        self.assertEqual(data["cues"][0]["start_ms"], 1000)
        self.assertEqual(data["cues"][0]["end_ms"], 4000)

        transcript_id = data["transcript_id"]

        # List projects
        listed = self.client.get("/api/transcripts/projects?project_id=proj-1")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["transcript_id"], transcript_id)

    def test_cue_editing_operations_and_revision_lock(self) -> None:
        # Create project with 2 cues
        project = TranscriptProject.create(
            project_id="proj-1",
            name="Test Cues",
            source_path="",
            source_kind="manual",
            requested_language="vi",
            model_id="base",
            requested_device="auto",
            diarization_requested=False,
            cues=(
                TranscriptCue(
                    "cue-1",
                    0,
                    1000,
                    3000,
                    "Đoạn 1",
                    words=(
                        TranscriptWord("word-1", "Đoạn", 1000, 1800),
                        TranscriptWord("word-2", "1", 2100, 2800),
                    ),
                ),
                TranscriptCue("cue-2", 1, 3500, 5000, "Đoạn 2"),
            ),
        )
        repo = TranscriptRepository(self.root / "transcript_projects.json")
        repo.create(project)

        transcript_id = project.transcript_id

        # 1. Edit cue text
        edit_res = self.client.patch(
            f"/api/transcripts/projects/{transcript_id}/cues/cue-1",
            json={"text": "Đoạn 1 đã sửa", "expected_revision": 1},
        )
        self.assertEqual(edit_res.status_code, 200)
        self.assertEqual(edit_res.json()["cues"][0]["text"], "Đoạn 1 đã sửa")
        self.assertEqual(edit_res.json()["revision"], 2)

        # 2. Revision mismatch fails (optimistic locking)
        conflict_res = self.client.patch(
            f"/api/transcripts/projects/{transcript_id}/cues/cue-1",
            json={"text": "Sửa lại lần nữa", "expected_revision": 1},
        )
        self.assertEqual(conflict_res.status_code, 409)

        # 3. Split cue
        split_res = self.client.post(
            f"/api/transcripts/projects/{transcript_id}/cues/cue-1/split",
            json={
                "split_ms": 2000,
                "first_text": "Phần đầu",
                "second_text": "Phần sau",
                "expected_revision": 2,
            },
        )
        self.assertEqual(split_res.status_code, 200)
        self.assertEqual(len(split_res.json()["cues"]), 3)
        self.assertEqual(split_res.json()["cues"][0]["text"], "Phần đầu")
        self.assertEqual(split_res.json()["cues"][0]["end_ms"], 2000)
        self.assertEqual(split_res.json()["cues"][1]["text"], "Phần sau")
        self.assertEqual(split_res.json()["cues"][1]["start_ms"], 2000)
        self.assertEqual(len(split_res.json()["cues"][0]["words"]), 1)
        self.assertEqual(len(split_res.json()["cues"][1]["words"]), 1)

        # 4. Merge cues
        cues = split_res.json()["cues"]
        merge_res = self.client.post(
            f"/api/transcripts/projects/{transcript_id}/merge-cues",
            json={
                "first_cue_id": cues[0]["cue_id"],
                "second_cue_id": cues[1]["cue_id"],
                "separator": " - ",
                "expected_revision": 3,
            },
        )
        self.assertEqual(merge_res.status_code, 200)
        self.assertEqual(len(merge_res.json()["cues"]), 2)
        self.assertEqual(merge_res.json()["cues"][0]["text"], "Phần đầu - Phần sau")
        self.assertEqual(len(merge_res.json()["cues"][0]["words"]), 2)

        reordered = list(reversed(merge_res.json()["cues"]))
        for position, cue in enumerate(reordered):
            cue["position"] = position
        reorder_res = self.client.put(
            f"/api/transcripts/projects/{transcript_id}/document",
            json={
                "cues": reordered,
                "speakers": merge_res.json()["speakers"],
                "expected_revision": 4,
            },
        )
        self.assertEqual(reorder_res.status_code, 200, reorder_res.text)
        self.assertEqual(
            [cue["cue_id"] for cue in reorder_res.json()["cues"]],
            [cue["cue_id"] for cue in reordered],
        )

    def test_export_formats_and_dubbing_handoff(self) -> None:
        project = TranscriptProject.create(
            project_id="proj-1",
            name="Export Test",
            source_path="",
            source_kind="manual",
            requested_language="vi",
            model_id="base",
            requested_device="auto",
            diarization_requested=False,
            cues=(
                TranscriptCue("cue-1", 0, 1000, 3000, "Xin chào"),
                TranscriptCue("cue-2", 1, 4000, 6000, "Tạm biệt"),
            ),
        )
        repo = TranscriptRepository(self.root / "transcript_projects.json")
        repo.create(project)
        t_id = project.transcript_id

        # Export SRT
        srt = self.client.get(f"/api/transcripts/projects/{t_id}/export?format=srt")
        self.assertEqual(srt.status_code, 200)
        self.assertIn("00:00:01,000 --> 00:00:03,000", srt.text)
        self.assertIn("Xin chào", srt.text)

        # Export VTT
        vtt = self.client.get(f"/api/transcripts/projects/{t_id}/export?format=vtt")
        self.assertEqual(vtt.status_code, 200)
        self.assertIn("WEBVTT", vtt.text)
        self.assertIn("00:00:01.000 --> 00:00:03.000", vtt.text)

        # Export TXT
        txt = self.client.get(f"/api/transcripts/projects/{t_id}/export?format=txt")
        self.assertEqual(txt.status_code, 200)
        self.assertIn("Xin chào", txt.text)

        # Dubbing handoff
        handoff = self.client.get(f"/api/transcripts/projects/{t_id}/dubbing-handoff")
        self.assertEqual(handoff.status_code, 200)
        segments = handoff.json()
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["source_text"], "Xin chào")
        self.assertEqual(segments[0]["start_ms"], 1000)

    def test_vtt_speakers_document_save_and_recorded_handoffs(self) -> None:
        response = self.client.post(
            "/api/transcripts/import-text",
            json={
                "project_id": "proj-speakers",
                "name": "Cuộc trò chuyện",
                "content": (
                    "WEBVTT\n\n"
                    "00:00.000 --> 00:02.000\n<v Lan>Xin chào\n\n"
                    "00:02.500 --> 00:05.000\n<v Minh>Chào Lan\n"
                ),
                "format_type": "vtt",
                "language": "vi",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        project = response.json()
        self.assertEqual([speaker["label"] for speaker in project["speakers"]], ["Lan", "Minh"])

        cues = project["cues"]
        cues[1]["text"] = "Chào Lan, rất vui được gặp bạn"
        cues[1]["end_ms"] = 6500
        saved = self.client.put(
            f'/api/transcripts/projects/{project["transcript_id"]}/document',
            json={
                "cues": cues,
                "speakers": project["speakers"],
                "expected_revision": 1,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 2)
        self.assertEqual(saved.json()["duration_ms"], 6500)

        conflict = self.client.put(
            f'/api/transcripts/projects/{project["transcript_id"]}/document',
            json={"cues": cues, "speakers": project["speakers"], "expected_revision": 1},
        )
        self.assertEqual(conflict.status_code, 409)

        dubbing = self.client.post(
            f'/api/transcripts/projects/{project["transcript_id"]}/handoffs/dubbing'
        )
        self.assertEqual(dubbing.status_code, 200, dubbing.text)
        self.assertIn("Lan: Xin chào", dubbing.json()["srt_text"])
        self.assertEqual(dubbing.json()["segments"][0]["speaker_id"], "Lan")
        self.assertEqual(len(dubbing.json()["segments"]), 2)

        longform = self.client.post(
            f'/api/transcripts/projects/{project["transcript_id"]}/handoffs/longform'
        )
        self.assertEqual(longform.status_code, 200, longform.text)
        self.assertIn("Lan: Xin chào", longform.json()["text"])
        self.assertIn("[pause 500ms]", longform.json()["text"])

        detail = self.client.get(
            f'/api/transcripts/projects/{project["transcript_id"]}'
        ).json()
        self.assertEqual([item["target"] for item in detail["handoffs"]], ["dubbing", "longform"])
        reopened = self.client.get(
            f'/api/transcripts/projects/{project["transcript_id"]}/handoffs/longform'
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()["handoff_id"], longform.json()["handoff_id"])

        exported = self.client.get(
            f'/api/transcripts/projects/{project["transcript_id"]}/export?format=srt'
        )
        self.assertEqual(exported.status_code, 200)
        self.assertIn("filename*=UTF-8''", exported.headers["content-disposition"])

    def test_long_transcript_list_is_summary_only(self) -> None:
        content = "\n".join(f"Dòng transcript {index}" for index in range(1000))
        created = self.client.post(
            "/api/transcripts/import-text",
            json={
                "project_id": "proj-long",
                "name": "Transcript dài",
                "content": content,
                "format_type": "txt",
                "language": "vi",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["cue_count"], 1000)

        listed = self.client.get("/api/transcripts/projects?project_id=proj-long")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["cue_count"], 1000)
        self.assertNotIn("cues", listed.json()[0])

    def test_repository_serializes_revision_checks_across_instances(self) -> None:
        path = self.root / "concurrent_transcripts.json"
        project = TranscriptProject.create(
            project_id="proj-concurrent",
            name="Concurrent",
            source_path="",
            source_kind="manual",
            requested_language="vi",
            model_id="base",
            requested_device="cpu",
            diarization_requested=False,
            cues=(TranscriptCue("cue-1", 0, 0, 1000, "Gốc"),),
        )
        TranscriptRepository(path).create(project)

        def write(label: str) -> str:
            repository = TranscriptRepository(path)
            try:
                updated = repository.mutate(
                    project.transcript_id,
                    lambda current: self._slow_rename(current, label),
                    expected_revision=1,
                )
                return updated.name
            except RevisionConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(write, ("Writer A", "Writer B")))
        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(TranscriptRepository(path).get(project.transcript_id).revision, 2)

    @staticmethod
    def _slow_rename(project: TranscriptProject, name: str) -> TranscriptProject:
        time.sleep(0.03)
        return project.evolved(name=name)

    def test_delete_removes_speaker_reference_artifacts(self) -> None:
        response = self.client.post(
            "/api/transcripts/import-text",
            json={
                "project_id": "proj-delete",
                "name": "Delete me",
                "content": "Một dòng",
                "format_type": "txt",
                "language": "vi",
            },
        )
        transcript_id = response.json()["transcript_id"]
        repository = TranscriptRepository(self.root / "transcript_projects.json")
        artifact_dir = repository.project_dir(transcript_id)
        artifact = artifact_dir / "speaker-references" / "speaker-1.wav"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"RIFF")

        deleted = self.client.delete(f"/api/transcripts/projects/{transcript_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(artifact_dir.exists())

    def test_import_requires_active_project(self) -> None:
        response = self.client.post(
            "/api/transcripts/import-text",
            json={"name": "Không project", "content": "Một dòng", "format_type": "txt"},
        )
        self.assertEqual(response.status_code, 422)

    def test_asr_task_serializes_created_transcript_for_ui(self) -> None:
        media = self.root / "speech.wav"
        media.write_bytes(b"RIFF")
        record = SimpleNamespace(task_id="task-asr", stop_event=threading.Event())
        with (
            mock.patch.object(transcript_router.task_registry, "create", return_value=record),
            mock.patch.object(transcript_router.task_registry, "submit") as submit,
        ):
            response = self.client.post(
                "/api/transcripts/import-media",
                json={"project_id": "proj-asr", "media_path": str(media)},
            )
        self.assertEqual(response.status_code, 200)
        serializer = submit.call_args.args[2]
        project = TranscriptProject.create(
            project_id="proj-asr",
            name="ASR",
            source_path=str(media),
            source_kind="audio",
            requested_language="auto",
            model_id="base",
            requested_device="cpu",
            diarization_requested=False,
            cues=(TranscriptCue("cue-1", 0, 0, 1000, "Xin chào"),),
        )
        self.assertEqual(serializer(project)["transcript_id"], project.transcript_id)

    def test_diarization_keeps_fallback_speaker_for_unmatched_cues(self) -> None:
        media = self.root / "speech.mp4"
        media.write_bytes(b"video")
        repository = TranscriptRepository(self.root / "diarized.json")
        service = TranscriptService(repository)
        cues = [
            TranscriptCue("cue-1", 0, 0, 1000, "Khớp turn"),
            TranscriptCue("cue-2", 1, 2000, 3000, "Không khớp turn"),
        ]
        turns = (SpeakerTurn("SPEAKER_00", 0, 1000),)
        with (
            mock.patch("app.transcripts.service.find_ffmpeg", return_value="ffmpeg"),
            mock.patch("app.transcripts.service._run_ffmpeg"),
            mock.patch.object(
                service,
                "_transcribe_detailed",
                return_value=(cues, "vi", "cpu"),
            ),
            mock.patch.object(
                service,
                "_diarize",
                return_value=(turns, "complete", ""),
            ),
        ):
            project = service.import_media(
                project_id="proj-diarization",
                media_path=media,
                diarization=True,
            )
        self.assertEqual(
            {speaker.speaker_id for speaker in project.speakers},
            {"SPEAKER_00", "speaker-1"},
        )
        self.assertEqual([cue.speaker_id for cue in project.cues], ["SPEAKER_00", "speaker-1"])


if __name__ == "__main__":
    unittest.main()
