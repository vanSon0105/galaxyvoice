"""OmniVoice workspaces router tests (repository, gallery, transcripts,
documents) with a tmp config path; render is monkeypatched."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app.omnivoice.runtime import OmniVoiceRuntime
from app.server.main import create_app
from app.server.routers import omnivoice_workspaces as workspaces_router
from app.server.tasks import DONE, task_registry


def _wait_status(task_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish in time")


class WorkspacesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_workspaces_")
        self.tmp = Path(self._tmp.name)
        self.client = TestClient(create_app(config_path=self.tmp / "config.json"))
        task_registry._tasks.clear()
        with workspaces_router._documents_lock:
            workspaces_router._documents.clear()
        self._runtime_patcher = mock.patch.object(
            workspaces_router,
            "_runtime",
            return_value=OmniVoiceRuntime.from_base(self.tmp),
        )
        self._runtime_patcher.start()
        self._client_patcher = mock.patch.object(workspaces_router, "_worker_client")
        self.fake_client = self._client_patcher.start()
        self.fake_client.return_value = mock.Mock()

    def tearDown(self) -> None:
        self._client_patcher.stop()
        self._runtime_patcher.stop()
        self.client.close()
        self._tmp.cleanup()

    def test_project_save_list_get_delete(self) -> None:
        saved = self.client.post(
            "/api/workspaces/projects",
            json={"workspace": "stories", "name": "Truyện thử", "payload": {"api_key": "sk-secret"}},
        )
        self.assertEqual(saved.status_code, 200)
        body = saved.json()
        self.assertEqual(body["workspace"], "stories")
        self.assertNotIn("api_key", body["payload"])

        listed = self.client.get("/api/workspaces/projects", params={"workspace": "stories"})
        self.assertEqual(len(listed.json()), 1)

        fetched = self.client.get(f"/api/workspaces/projects/{body['project_id']}")
        self.assertEqual(fetched.json()["name"], "Truyện thử")

        updated = self.client.post(
            "/api/workspaces/projects",
            json={
                "workspace": "stories",
                "name": "Truyện sửa",
                "project_id": body["project_id"],
                "payload": {},
            },
        )
        self.assertEqual(updated.json()["name"], "Truyện sửa")
        self.assertEqual(len(self.client.get("/api/workspaces/projects").json()), 1)

        self.assertEqual(
            self.client.delete(f"/api/workspaces/projects/{body['project_id']}").status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/workspaces/projects").json(), [])

    def test_history_add_star_search_clear(self) -> None:
        added = self.client.post(
            "/api/workspaces/history",
            json={"workspace": "audiobook", "title": "Chương 1", "summary": "bắt đầu", "artifact_path": ""},
        )
        self.assertEqual(added.status_code, 200)
        history_id = added.json()["history_id"]

        starred = self.client.patch(
            f"/api/workspaces/history/{history_id}/starred",
            json={"starred": True},
        )
        self.assertTrue(starred.json()["starred"])

        search = self.client.get(
            "/api/workspaces/history",
            params={"query": "bắt đầu", "starred_only": True},
        )
        self.assertEqual(len(search.json()), 1)

        self.client.delete("/api/workspaces/history", params={"workspace": "audiobook"})
        self.assertEqual(self.client.get("/api/workspaces/history").json(), [])

    def test_gallery_returns_paginated_archetypes(self) -> None:
        response = self.client.get("/api/workspaces/gallery", params={"page": 1})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body["total"], 0)
        self.assertEqual(len(body["items"]), min(body["total"], 120))
        self.assertIn("instruct", body["items"][0])
        categories = self.client.get("/api/workspaces/gallery/categories").json()
        self.assertIsInstance(categories, list)

    def test_transcripts_add_search_delete_clear(self) -> None:
        added = self.client.post(
            "/api/workspaces/transcripts",
            json={"text": "Nội dung ghi âm", "language": "vi"},
        )
        self.assertEqual(added.status_code, 200)
        entry_id = added.json()["entry_id"]
        self.assertEqual(
            len(self.client.get("/api/workspaces/transcripts", params={"query": "ghi âm"}).json()),
            1,
        )
        self.client.delete(f"/api/workspaces/transcripts/{entry_id}")
        self.assertEqual(self.client.get("/api/workspaces/transcripts").json(), [])

    def test_document_lifecycle_and_ops(self) -> None:
        source = "# Mở đầu\nLan: Chào bạn.\n[pause 500ms]\nMinh: Chào Lan.\n"
        created = self.client.post(
            "/api/workspaces/document",
            json={"kind": "stories", "source": source},
        )
        self.assertEqual(created.status_code, 200)
        doc = created.json()
        self.assertEqual(doc["kind"], "stories")
        self.assertEqual(len(doc["document"]["items"]), 2)

        first_id = doc["document"]["items"][0]["item_id"]
        updated = self.client.post(
            f"/api/workspaces/document/{doc['doc_id']}/ops",
            json={"op": "update", "item_id": first_id, "changes": {"text": "Đổi lời thoại."}},
        )
        self.assertEqual(updated.json()["document"]["items"][0]["text"], "Đổi lời thoại.")

        added = self.client.post(
            f"/api/workspaces/document/{doc['doc_id']}/ops",
            json={"op": "add", "after_id": first_id, "chapter": "Mở đầu"},
        )
        self.assertEqual(len(added.json()["document"]["items"]), 3)

        deleted = self.client.post(
            f"/api/workspaces/document/{doc['doc_id']}/ops",
            json={"op": "delete", "item_id": first_id},
        )
        self.assertEqual(len(deleted.json()["document"]["items"]), 2)

        self.assertEqual(
            self.client.get(f"/api/workspaces/document/{doc['doc_id']}").status_code,
            200,
        )

    def test_document_op_hydrates_current_pronunciation_rules(self) -> None:
        created = self.client.post(
            "/api/workspaces/document",
            json={"kind": "stories", "source": "Lan: Galaxy bắt đầu.\n"},
        ).json()
        document = created["document"]
        document["pronunciation_rules"] = [
            {
                "rule_id": "pron-galaxy",
                "source": "Galaxy",
                "replacement": "Ga la xi",
                "language": "vi",
                "case_sensitive": False,
                "whole_word": True,
            }
        ]
        response = self.client.post(
            f"/api/workspaces/document/{created['doc_id']}/ops",
            params={"kind": "stories"},
            json={
                "op": "update",
                "item_id": document["items"][0]["item_id"],
                "changes": {"emphasis": True},
                "document": document,
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["document"]["pronunciation_rules"][0]["replacement"], "Ga la xi")
        self.assertTrue(body["document"]["items"][0]["emphasis"])

    def test_longform_project_is_revisioned_and_preview_does_not_replace_final_result(self) -> None:
        source = "# Mở đầu\nLan: Chào bạn.\nMinh: Tạm biệt.\n"
        document = self.client.post(
            "/api/workspaces/document",
            json={"kind": "stories", "source": source},
        ).json()["document"]
        created = self.client.post(
            "/api/workspaces/longform/projects",
            json={
                "name": "Truyện dài",
                "kind": "stories",
                "stage": "plan",
                "source": source,
                "document": document,
                "language": "vi",
                "last_result": {"project_dir": "untrusted"},
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        project = created.json()
        self.assertEqual(project["revision"], 1)
        self.assertEqual(project["last_result"], {})
        self.assertEqual(
            self.client.get("/api/workspaces/longform/projects", params={"kind": "stories"}).json()[0]["item_count"],
            2,
        )

        stale = self.client.post(
            "/api/workspaces/longform/projects",
            json={
                "project_id": project["project_id"],
                "expected_revision": 0,
                "name": "Bản cũ",
                "kind": "stories",
                "source": source,
                "document": document,
            },
        )
        self.assertEqual(stale.status_code, 409)

        render_dir = self.tmp / "preview-render"
        render_dir.mkdir()
        wav_path = render_dir / "combined.wav"
        wav_path.write_bytes(b"RIFF-preview")
        from app.omnivoice.workspaces.renderer import LongformWorkspaceResult

        fake_result = LongformWorkspaceResult(
            project_dir=render_dir,
            wav_path=wav_path,
            srt_path=render_dir / "combined.srt",
            manifest_path=render_dir / "workspace_manifest.json",
            item_results=(SimpleNamespace(wav_path=wav_path),),
        )
        with mock.patch.object(
            workspaces_router, "render_longform_plan", return_value=fake_result
        ) as render:
            preview = self.client.post(
                "/api/workspaces/render",
                json={
                    "project_id": project["project_id"],
                    "kind": "stories",
                    "output_dir": str(self.tmp),
                    "preview_item_index": 1,
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(_wait_status(preview.json()["task_id"]), DONE)

        preview_plan = render.call_args.args[1]
        self.assertEqual(len(preview_plan.spans), 1)
        self.assertEqual(preview_plan.spans[0].display_text, "Tạm biệt.")
        stored = self.client.get(
            f"/api/workspaces/longform/projects/{project['project_id']}"
        ).json()
        self.assertEqual(stored["last_result"], {})

    def test_longform_and_dubbing_projects_are_scoped_to_active_project(self) -> None:
        longform = self.client.post(
            "/api/workspaces/longform/projects",
            json={
                "galaxy_project_id": "active-project-1",
                "name": "Longform",
                "kind": "stories",
                "stage": "plan",
                "source": "Narrator: Hello",
                "document": {"chapters": [], "items": []},
            },
        )
        self.assertEqual(longform.status_code, 200, longform.text)
        self.assertEqual(longform.json()["galaxy_project_id"], "active-project-1")
        self.assertEqual(
            len(
                self.client.get(
                    "/api/workspaces/longform/projects",
                    params={"galaxy_project_id": "active-project-1"},
                ).json()
            ),
            1,
        )
        self.assertEqual(
            self.client.get(
                "/api/workspaces/longform/projects",
                params={"galaxy_project_id": "other-project"},
            ).json(),
            [],
        )

        dubbing = self.client.post(
            "/api/workspaces/dubbing/projects",
            json={
                "galaxy_project_id": "active-project-1",
                "name": "Dubbing",
                "stage": "ingest",
                "source_srt": "source",
                "segments": [],
            },
        )
        self.assertEqual(dubbing.status_code, 200, dubbing.text)
        self.assertEqual(dubbing.json()["galaxy_project_id"], "active-project-1")
        self.assertEqual(
            len(
                self.client.get(
                    "/api/workspaces/dubbing/projects",
                    params={"galaxy_project_id": "active-project-1"},
                ).json()
            ),
            1,
        )
        self.assertEqual(
            self.client.get(
                "/api/workspaces/dubbing/projects",
                params={"galaxy_project_id": "other-project"},
            ).json(),
            [],
        )

    def test_render_uses_document_and_serializes_result(self) -> None:
        created = self.client.post(
            "/api/workspaces/document",
            json={"kind": "stories", "source": "Lan: Chào bạn.\n"},
        )
        doc_id = created.json()["doc_id"]
        from app.omnivoice.workspaces.renderer import LongformWorkspaceResult

        fake_result = LongformWorkspaceResult(
            project_dir=self.tmp / "longform",
            wav_path=self.tmp / "longform" / "combined.wav",
            srt_path=self.tmp / "longform" / "combined.srt",
            manifest_path=self.tmp / "longform" / "manifest.json",
            item_results=(),
        )
        with mock.patch.object(
            workspaces_router, "render_longform_plan", return_value=fake_result
        ) as render:
            response = self.client.post(
                "/api/workspaces/render",
                json={"doc_id": doc_id, "kind": "stories", "output_dir": str(self.tmp)},
            )
            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)
            self.assertEqual(render.call_args.kwargs["stop_event"], task_registry.get(task_id).stop_event)

    def test_dubbing_plan_endpoint(self) -> None:
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\nChào bạn\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nTạm biệt\n"
        )
        response = self.client.get("/api/workspaces/dubbing/plan", params={"srt_text": srt})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["segments"]), 2)
        self.assertEqual(body["segments"][0]["text"], "Chào bạn")
        self.assertEqual(body["segments"][0]["end_ms"], 2000)

    def test_dubbing_plan_accepts_external_translation_and_runs_qc(self) -> None:
        source = "1\n00:00:00,000 --> 00:00:01,000\nLan: Hello\n"
        translated = "1\n00:00:00,000 --> 00:00:01,000\nXin chao\n"
        response = self.client.post(
            "/api/workspaces/dubbing/plan",
            json={"source_srt": source, "translated_srt": translated},
        )
        self.assertEqual(response.status_code, 200, response.text)
        segment = response.json()["segments"][0]
        self.assertEqual(segment["source_text"], "Hello")
        self.assertEqual(segment["text"], "Xin chao")
        self.assertEqual(segment["speaker_id"], "Lan")
        quality = self.client.post(
            "/api/workspaces/dubbing/qc",
            json={"segments": [{**segment, "profile_id": "lan"}]},
        )
        self.assertEqual(quality.status_code, 200, quality.text)
        self.assertEqual(quality.json()["segment_count"], 1)

        mismatched = self.client.post(
            "/api/workspaces/dubbing/plan",
            json={
                "source_srt": source,
                "translated_srt": "2\n00:00:00,000 --> 00:00:01,000\nXin chao\n",
            },
        )
        self.assertEqual(mismatched.status_code, 422)

    def test_dubbing_project_is_revisioned_and_persistent(self) -> None:
        body = {
            "name": "Dub 1",
            "stage": "cast",
            "source_srt": "source",
            "segments": [
                {
                    "segment_id": "a",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "source_text": "Hello",
                    "text": "Xin chao",
                    "speaker_id": "Lan",
                    "profile_id": "lan",
                }
            ],
        }
        created = self.client.post("/api/workspaces/dubbing/projects", json=body)
        self.assertEqual(created.status_code, 200, created.text)
        project = created.json()
        self.assertEqual(project["revision"], 1)
        listed = self.client.get("/api/workspaces/dubbing/projects").json()
        self.assertEqual(listed[0]["segment_count"], 1)
        render_dir = self.tmp / "dub-render"
        render_dir.mkdir()
        voice_path = render_dir / "combined.wav"
        voice_path.write_bytes(b"RIFF-test")
        updated = self.client.post(
            "/api/workspaces/dubbing/projects",
            json={
                **body,
                "project_id": project["project_id"],
                "expected_revision": 1,
                "stage": "qc",
                "last_result": {
                    "project_dir": str(render_dir),
                    "wav_path": str(voice_path),
                },
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["revision"], 2)
        self.assertEqual(updated.json()["last_result"], {})

        # Artifact paths are attached by the render task, never accepted from
        # a browser payload used to save editable project state.
        repository = workspaces_router.DubbingProjectRepository(self.tmp / "dubbing_projects.json")
        stored = repository.get(project["project_id"])
        self.assertIsNotNone(stored)
        repository.save(
            stored.evolved(
                last_result={
                    "project_dir": str(render_dir),
                    "wav_path": str(voice_path),
                }
            ),
            expected_revision=stored.revision,
        )
        media = self.client.get(
            f"/api/workspaces/dubbing/projects/{project['project_id']}/media/voice"
        )
        self.assertEqual(media.status_code, 200, media.text)
        self.assertEqual(media.content, b"RIFF-test")
        stale = self.client.post(
            "/api/workspaces/dubbing/projects",
            json={**body, "project_id": project["project_id"], "expected_revision": 1},
        )
        self.assertEqual(stale.status_code, 409)

    def test_dubbing_ai_translation_returns_task_payload(self) -> None:
        source = "1\n00:00:00,000 --> 00:00:01,000\nHello\n"
        translated = [workspaces_router.parse_srt("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n")[0]]
        with (
            mock.patch.object(workspaces_router, "validate_translation_options"),
            mock.patch.object(workspaces_router, "translate_cues", return_value=translated),
        ):
            response = self.client.post(
                "/api/workspaces/dubbing/translate",
                json={"source_srt": source, "provider": "deepseek", "api_key": "test", "target_language": "vi"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)
            payload = task_registry.get(task_id).result
            self.assertEqual(payload["segments"][0]["text"], "Xin chao")

    def test_import_source_missing_file_returns_404(self) -> None:
        response = self.client.post(
            "/api/workspaces/import-source",
            json={"path": str(self.tmp / "khong-co.txt")},
        )
        self.assertEqual(response.status_code, 404)

    def test_worker_path_points_at_real_worker_file(self) -> None:
        # Regression guard: the router used to resolve app/server/omnivoice/worker.py.
        path = workspaces_router._worker_path()
        self.assertEqual(path.name, "worker.py")
        self.assertTrue(path.is_file(), f"worker không tồn tại: {path}")


if __name__ == "__main__":
    unittest.main()
