from __future__ import annotations

import re
import shutil
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..common.cache import write_json_atomic
from ..common.errors import TaskCancelledError
from ..common.paths import unique_project_dir
from ..studio.execution import (
    DEFAULT_PERSIST_INTERVAL_SECONDS,
    DEFAULT_SPEECH_WORKERS,
    IntervalGate,
    prewarm_engine,
    speech_worker_count,
)
from ..studio.models import StudioArtifact, StudioGenerationSpec, StudioVoiceSelection
from ..studio.render_cache import SpeechRenderCache
from ..studio.service import StudioEngine
from ..voice.audio import split_wav_on_silence
from ..voice.text_splitter import normalize_text
from .speech_planning import ShortCueLimits, SpeechCueGroup, plan_short_cues


EditorSpeechProgress = Callable[[str, float], None]
EditorSpeechCheckpoint = Callable[[dict[str, object]], None]
EditorSpeechControl = Callable[[], None]
EditorSpeechItemCallback = Callable[["EditorSpeechItemResult"], None]
_SAFE_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CLUSTER_PAUSE_MS = 180


class _UnprovenClusterAlignment(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorSpeechCueSpec:
    item_id: str
    track_id: str
    cue_id: str
    start_ms: int
    text: str
    language: str = ""
    end_ms: int = 0

    def validate(self) -> None:
        if not _SAFE_ITEM_ID.fullmatch(self.item_id):
            raise ValueError(f"ID audio không hợp lệ: {self.item_id}")
        if not self.track_id.strip() or not self.cue_id.strip():
            raise ValueError("Mỗi câu phụ đề phải giữ track_id và cue_id.")
        if self.start_ms < 0:
            raise ValueError("Thời điểm bắt đầu audio không được âm.")
        if self.end_ms and self.end_ms <= self.start_ms:
            raise ValueError("Thời điểm kết thúc audio phải sau thời điểm bắt đầu.")
        if not self.text.strip():
            raise ValueError(f"Câu {self.cue_id} chưa có nội dung.")


@dataclass(frozen=True)
class EditorSpeechSpec:
    job_id: str
    project_id: str
    title: str
    output_dir: str
    engine_id: str = "omnivoice"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    max_workers: int = DEFAULT_SPEECH_WORKERS
    voice_revision: int = 1
    voice: StudioVoiceSelection = field(default_factory=StudioVoiceSelection)
    engine_options: dict[str, Any] = field(default_factory=dict)
    cues: tuple[EditorSpeechCueSpec, ...] = ()

    def validate(self) -> None:
        if not self.job_id.strip():
            raise ValueError("Editor speech job chưa có ID.")
        if not self.project_id.strip():
            raise ValueError("Hãy chọn hoặc tạo project trước khi tạo giọng.")
        if not self.output_dir.strip():
            raise ValueError("Hãy chọn thư mục xuất trước khi tạo giọng.")
        if not self.engine_id.strip():
            raise ValueError("Editor speech job chưa chỉ định engine.")
        if not 0.5 <= self.speed <= 1.5:
            raise ValueError("Tốc độ phải từ 0.5 đến 1.5.")
        if not self.cues:
            raise ValueError("Không có câu phụ đề nào để tạo giọng.")
        item_ids: set[str] = set()
        for cue in self.cues:
            cue.validate()
            if cue.item_id in item_ids:
                raise ValueError(f"ID audio bị trùng: {cue.item_id}")
            item_ids.add(cue.item_id)

    def generation_spec(self, cue: EditorSpeechCueSpec, root_dir: Path) -> StudioGenerationSpec:
        return StudioGenerationSpec(
            project_id=self.project_id,
            title=cue.item_id,
            text=cue.text,
            engine_id=self.engine_id,
            language=cue.language or self.language,
            output_dir=str(root_dir),
            output_name=cue.item_id,
            model_id=self.model_id,
            device=self.device,
            speed=self.speed,
            formats=("wav",),
            voice=self.voice,
            engine_options=dict(self.engine_options),
        )


@dataclass(frozen=True)
class EditorSpeechItemResult:
    item_id: str
    track_id: str
    cue_id: str
    start_ms: int
    status: str
    wav_path: str = ""
    error: str = ""
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["wav_path"] = self.wav_path or None
        payload["error"] = self.error or None
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class EditorSpeechResult:
    job_id: str
    project_id: str
    root_dir: str
    items: tuple[EditorSpeechItemResult, ...]

    @property
    def completed_count(self) -> int:
        return sum(item.status == "done" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)

    @property
    def status(self) -> str:
        if self.completed_count == len(self.items):
            return "completed"
        if self.completed_count:
            return "partial"
        return "failed"

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "root_dir": self.root_dir,
            "status": self.status,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "total_count": len(self.items),
            "items": [item.to_payload() for item in self.items],
        }


class EditorSpeechService:
    def __init__(
        self,
        *,
        checkpoint_interval_seconds: float = DEFAULT_PERSIST_INTERVAL_SECONDS,
        render_cache: SpeechRenderCache | None = None,
        short_cue_limits: ShortCueLimits | None = None,
    ) -> None:
        self.checkpoint_interval_seconds = checkpoint_interval_seconds
        self.render_cache = render_cache
        self.short_cue_limits = short_cue_limits or ShortCueLimits()

    def execute(
        self,
        spec: EditorSpeechSpec,
        engine: StudioEngine,
        *,
        progress: EditorSpeechProgress | None = None,
        checkpoint: EditorSpeechCheckpoint | None = None,
        control: EditorSpeechControl | None = None,
        stop_event: threading.Event | None = None,
        item_finished: EditorSpeechItemCallback | None = None,
    ) -> EditorSpeechResult:
        spec.validate()
        if engine.engine_id != spec.engine_id:
            raise ValueError(f"Adapter {engine.engine_id} không xử lý được {spec.engine_id}.")

        root = unique_project_dir(Path(spec.output_dir).expanduser(), spec.title, "editor-speech")
        total = len(spec.cues)
        self._check_control(control, stop_event)
        first_spec = spec.generation_spec(spec.cues[0], root)
        first_spec.validate()
        if progress and total >= 3:
            progress("Đang chuẩn bị engine tạo giọng...", 0.0)
        prewarm_engine(
            engine,
            first_spec,
            total,
            lambda message: progress(message, 0.0) if progress else None,
        )

        results: dict[str, EditorSpeechItemResult] = {}
        checkpoint_gate = IntervalGate(self.checkpoint_interval_seconds)

        def save_checkpoint(last_item_id: str, *, force: bool = False) -> None:
            if not checkpoint or not checkpoint_gate.ready(force=force):
                return
            checkpoint(
                {
                    "job_id": spec.job_id,
                    "last_item_id": last_item_id,
                    "completed": sum(item.status == "done" for item in results.values()),
                    "failed": sum(item.status == "failed" for item in results.values()),
                    "total": total,
                }
            )

        def finish(item: EditorSpeechItemResult) -> None:
            results[item.item_id] = item
            if item_finished:
                item_finished(item)
            save_checkpoint(item.item_id)
            if progress:
                progress(
                    f"Đã xử lý {len(results)}/{total} câu phụ đề.",
                    len(results) / total,
                )

        groups = plan_short_cues(spec.cues, self.short_cue_limits)
        positions = {cue.item_id: index for index, cue in enumerate(spec.cues)}
        worker_count = speech_worker_count(engine, spec.max_workers, len(groups))
        try:
            if worker_count == 1:
                for group in groups:
                    self._check_control(control, stop_event)
                    for item in self._generate_group(
                        spec,
                        group,
                        positions,
                        total,
                        root,
                        engine,
                        progress,
                        stop_event,
                    ):
                        finish(item)
            else:
                self._execute_parallel(
                    spec,
                    groups,
                    positions,
                    root,
                    engine,
                    worker_count,
                    finish,
                    progress,
                    control,
                    stop_event,
                )
        except TaskCancelledError:
            save_checkpoint(next(reversed(results), ""), force=True)
            raise

        save_checkpoint(next(reversed(results), ""), force=True)
        ordered = tuple(results[cue.item_id] for cue in spec.cues)
        result = EditorSpeechResult(spec.job_id, spec.project_id, str(root.resolve()), ordered)
        if progress:
            progress(
                f"Tạo giọng hoàn tất: {result.completed_count} thành công, {result.failed_count} lỗi.",
                1.0,
            )
        return result

    def _execute_parallel(
        self,
        spec: EditorSpeechSpec,
        groups: tuple[SpeechCueGroup[EditorSpeechCueSpec], ...],
        positions: dict[str, int],
        root: Path,
        engine: StudioEngine,
        worker_count: int,
        finish: EditorSpeechItemCallback,
        progress: EditorSpeechProgress | None,
        control: EditorSpeechControl | None,
        stop_event: threading.Event | None,
    ) -> None:
        total = len(spec.cues)
        pending = iter(enumerate(groups))
        futures: dict[Future[tuple[EditorSpeechItemResult, ...]], int] = {}

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="editor-speech") as executor:
            def submit_next() -> bool:
                self._check_control(control, stop_event)
                try:
                    group_index, group = next(pending)
                except StopIteration:
                    return False
                future = executor.submit(
                    self._generate_group,
                    spec,
                    group,
                    positions,
                    total,
                    root,
                    engine,
                    progress,
                    stop_event,
                )
                futures[future] = group_index
                return True

            for _ in range(worker_count):
                if not submit_next():
                    break

            while futures:
                self._check_control(control, stop_event)
                done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: futures[item]):
                    futures.pop(future)
                    for item in future.result():
                        finish(item)
                    submit_next()

    def _generate_group(
        self,
        spec: EditorSpeechSpec,
        group: SpeechCueGroup[EditorSpeechCueSpec],
        positions: dict[str, int],
        total: int,
        root: Path,
        engine: StudioEngine,
        progress: EditorSpeechProgress | None,
        stop_event: threading.Event | None,
    ) -> tuple[EditorSpeechItemResult, ...]:
        if not group.clustered:
            cue = group.cues[0]
            return (
                self._generate_item(
                    spec,
                    cue,
                    positions[cue.item_id],
                    total,
                    root,
                    engine,
                    progress,
                    stop_event,
                ),
            )

        context_text = "\n\n".join(normalize_text(cue.text) for cue in group.cues)
        cluster_name = f"context-{group.cues[0].item_id}-{len(group.cues)}"
        cluster_options = {
            **spec.engine_options,
            "_galaxy_cluster_pause_ms": _CLUSTER_PAUSE_MS,
        }
        generation_specs = tuple(
            replace(
                spec.generation_spec(cue, root),
                engine_options=cluster_options,
            )
            for cue in group.cues
        )
        cache_keys = tuple(
            self._cache_key(item_spec, spec.voice_revision, context_text, index)
            for index, item_spec in enumerate(generation_specs)
        )
        if self._restore_cluster_cache(group, generation_specs, cache_keys, root):
            if progress:
                progress(
                    f"Đã dùng cache cho {len(group.cues)} câu phụ đề.",
                    positions[group.cues[-1].item_id] / total,
                )
            return tuple(
                self._successful_item(cue, self._cache_destination(root, cue))
                for cue in group.cues
            )

        cluster_artifact: StudioArtifact | None = None
        try:
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            first_position = positions[group.cues[0].item_id]
            if progress:
                progress(
                    f"Đang tạo cụm {len(group.cues)} câu phụ đề...",
                    first_position / total,
                )
            cluster_spec = replace(
                generation_specs[0],
                title=cluster_name,
                text=context_text,
                output_name=cluster_name,
            )
            cluster_spec.validate()
            cluster_artifact = engine.generate(
                cluster_spec,
                lambda message: progress(message, first_position / total) if progress else None,
            )
            cluster_wav = self._validated_wav(cluster_artifact, root)
            output_paths = [self._cache_destination(root, cue) for cue in group.cues]
            split = split_wav_on_silence(
                cluster_wav,
                output_paths,
                weights=[max(1, len(normalize_text(cue.text))) for cue in group.cues],
            )
            if not split:
                raise _UnprovenClusterAlignment()

            results: list[EditorSpeechItemResult] = []
            for cue, output_path, key in zip(group.cues, output_paths, cache_keys):
                self._write_item_manifest(output_path, key, context_text)
                if self.render_cache is not None:
                    self.render_cache.store(key, output_path)
                results.append(self._successful_item(cue, output_path, cluster_artifact.warnings))
            return tuple(results)
        except TaskCancelledError:
            raise
        except Exception:
            if progress:
                progress(
                    "Không xác minh được ranh giới cụm; đang tạo riêng từng câu.",
                    positions[group.cues[0].item_id] / total,
                )
            self._clear_materialized_group(root, group)
            return tuple(
                self._generate_item(
                    spec,
                    cue,
                    positions[cue.item_id],
                    total,
                    root,
                    engine,
                    progress,
                    stop_event,
                )
                for cue in group.cues
            )
        finally:
            if cluster_artifact is not None:
                cluster_dir = cluster_artifact.project_dir.resolve()
                resolved_root = root.resolve()
                if cluster_dir != resolved_root and cluster_dir.is_relative_to(resolved_root):
                    shutil.rmtree(cluster_dir, ignore_errors=True)

    def _restore_cluster_cache(
        self,
        group: SpeechCueGroup[EditorSpeechCueSpec],
        generation_specs: tuple[StudioGenerationSpec, ...],
        cache_keys: tuple[str, ...],
        root: Path,
    ) -> bool:
        if self.render_cache is None or not all(self.render_cache.contains(key) for key in cache_keys):
            return False
        restored = all(
            self.render_cache.restore(key, self._cache_destination(root, cue))
            for cue, key in zip(group.cues, cache_keys)
        )
        if not restored:
            self._clear_materialized_group(root, group)
            return False
        for item_spec, cue, key in zip(generation_specs, group.cues, cache_keys):
            self._write_item_manifest(
                self._cache_destination(root, cue),
                key,
                normalize_text(item_spec.text),
            )
        return True

    @staticmethod
    def _clear_materialized_group(
        root: Path,
        group: SpeechCueGroup[EditorSpeechCueSpec],
    ) -> None:
        for cue in group.cues:
            shutil.rmtree(root / cue.item_id, ignore_errors=True)

    @staticmethod
    def _check_control(
        control: EditorSpeechControl | None,
        stop_event: threading.Event | None,
    ) -> None:
        if control:
            control()
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()

    def _generate_item(
        self,
        spec: EditorSpeechSpec,
        cue: EditorSpeechCueSpec,
        index: int,
        total: int,
        root: Path,
        engine: StudioEngine,
        progress: EditorSpeechProgress | None,
        stop_event: threading.Event | None,
    ) -> EditorSpeechItemResult:
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        if progress:
            progress(f"Đang tạo giọng {index + 1}/{total}", index / total)

        try:
            generation_spec = spec.generation_spec(cue, root)
            generation_spec.validate()
            cache_key = self._cache_key(generation_spec, spec.voice_revision)
            cache_path = self._cache_destination(root, cue)
            if self.render_cache is not None and self.render_cache.restore(cache_key, cache_path):
                self._write_item_manifest(cache_path, cache_key, "")
                if progress:
                    progress(f"Đã dùng cache cho câu {index + 1}/{total}.", index / total)
                return self._successful_item(cue, cache_path)
            artifact = engine.generate(
                generation_spec,
                lambda message: progress(message, index / total) if progress else None,
            )
            wav_path = self._validated_wav(artifact, root)
            if self.render_cache is not None:
                self.render_cache.store(cache_key, wav_path)
            return self._successful_item(cue, wav_path, artifact.warnings)
        except TaskCancelledError:
            raise
        except Exception as error:
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError() from error
            return EditorSpeechItemResult(
                item_id=cue.item_id,
                track_id=cue.track_id,
                cue_id=cue.cue_id,
                start_ms=cue.start_ms,
                status="failed",
                error=str(error),
            )

    def _cache_key(
        self,
        generation_spec: StudioGenerationSpec,
        voice_revision: int,
        context_text: str = "",
        context_index: int = 0,
    ) -> str:
        if self.render_cache is None:
            return ""
        return self.render_cache.key_for(
            generation_spec,
            voice_revision=voice_revision,
            context_text=context_text,
            context_index=context_index,
        )

    @staticmethod
    def _cache_destination(root: Path, cue: EditorSpeechCueSpec) -> Path:
        return root / cue.item_id / "voice.wav"

    @staticmethod
    def _validated_wav(artifact: StudioArtifact, root: Path) -> Path:
        wav_path = artifact.wav_path.resolve()
        if not wav_path.is_relative_to(root.resolve()) or not wav_path.is_file():
            raise ValueError("Engine trả về audio nằm ngoài thư mục của editor speech job.")
        return wav_path

    @staticmethod
    def _write_item_manifest(wav_path: Path, cache_key: str, context_text: str) -> None:
        write_json_atomic(
            wav_path.parent / "manifest.json",
            {
                "version": 1,
                "wav_path": str(wav_path),
                "cache_key": cache_key,
                "context": bool(context_text),
            },
        )

    @staticmethod
    def _successful_item(
        cue: EditorSpeechCueSpec,
        wav_path: Path,
        warnings: tuple[str, ...] = (),
    ) -> EditorSpeechItemResult:
        return EditorSpeechItemResult(
            item_id=cue.item_id,
            track_id=cue.track_id,
            cue_id=cue.cue_id,
            start_ms=cue.start_ms,
            status="done",
            wav_path=str(wav_path.resolve()),
            warnings=warnings,
        )
