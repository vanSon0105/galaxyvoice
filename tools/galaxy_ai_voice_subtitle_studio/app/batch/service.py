from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from ..common.errors import TaskCancelledError
from ..reliability.service import estimate_audio_bytes, guard_output_space
from ..studio.execution import (
    DEFAULT_PERSIST_INTERVAL_SECONDS,
    IntervalGate,
    prewarm_engine,
    speech_worker_count,
)
from ..studio.models import StudioArtifact
from ..studio.service import StudioEngine
from ..voice.audio import concatenate_wavs, try_convert_to_mp3
from .models import BatchItemState, BatchRun
from .repository import BatchRepository


BatchProgress = Callable[[str, float], None]
BatchCheckpoint = Callable[[dict[str, object]], None]
BatchControl = Callable[[], None]


class BatchService:
    def __init__(
        self,
        repository: BatchRepository,
        *,
        persistence_interval_seconds: float = DEFAULT_PERSIST_INTERVAL_SECONDS,
    ) -> None:
        self.repository = repository
        self.persistence_interval_seconds = persistence_interval_seconds

    def execute(
        self,
        batch_id: str,
        engine: StudioEngine,
        *,
        task_id: str,
        progress: BatchProgress | None = None,
        checkpoint: BatchCheckpoint | None = None,
        control: BatchControl | None = None,
        stop_event: threading.Event | None = None,
    ) -> BatchRun:
        run = self.repository.require(batch_id)
        pending_text = "\n".join(
            item.spec.text for item in run.items if item.status not in {"done", "failed"}
        )
        guard_output_space(
            run.spec.output_dir,
            required_bytes=estimate_audio_bytes(
                pending_text,
                output_count=len(run.spec.formats) + int(run.spec.combine),
            ),
        )
        if engine.engine_id != run.spec.engine_id:
            raise ValueError(f"Adapter {engine.engine_id} không xử lý được Batch {run.spec.engine_id}.")
        run.status = "running"
        run.task_id = task_id
        self.repository.save(run)
        total = len(run.items)

        persistence_gate = IntervalGate(self.persistence_interval_seconds)

        def persist(*, force: bool = False) -> None:
            if not persistence_gate.ready(force=force):
                return
            self.repository.save(run)
            if checkpoint:
                checkpoint(
                    {
                        "batch_id": run.batch_id,
                        "completed": run.completed_count,
                        "failed": run.failed_count,
                        "total": total,
                    }
                )

        pending = [
            (index, item)
            for index, item in enumerate(run.items)
            if item.status not in {"done", "failed"}
        ]

        try:
            if pending:
                self._check_control(control, stop_event)
                first_spec = run.spec.item_generation_spec(pending[0][1].spec, run.root_dir)
                first_spec.validate()
                if progress and len(pending) >= 3:
                    progress("Đang chuẩn bị engine tạo giọng...", 0.0)
                prewarm_engine(
                    engine,
                    first_spec,
                    len(pending),
                    (lambda message: progress(message, 0.0)) if progress else None,
                )
                worker_count = speech_worker_count(engine, run.spec.max_workers, len(pending))
                if worker_count == 1:
                    for index, item in pending:
                        self._check_control(control, stop_event)
                        self._prepare_item(item)
                        artifact, error = self._generate_item(
                            run, item, index, total, engine, progress, stop_event
                        )
                        self._finish_item(run, item, artifact, error)
                        persist()
                else:
                    self._execute_parallel(
                        run,
                        pending,
                        engine,
                        worker_count,
                        progress,
                        control,
                        stop_event,
                        persist,
                    )
            self._combine(run, progress)
            run.status = self._final_status(run)
            persist(force=True)
            if progress:
                progress(
                    f"Batch hoàn tất: {run.completed_count} thành công, {run.failed_count} lỗi.",
                    1.0,
                )
            return run
        except TaskCancelledError:
            run.status = "cancelled"
            for item in run.items:
                if item.status == "running":
                    item.status = "pending"
            persist(force=True)
            raise
        except Exception:
            run.status = "interrupted"
            for item in run.items:
                if item.status == "running":
                    item.status = "pending"
            persist(force=True)
            raise

    def _execute_parallel(
        self,
        run: BatchRun,
        pending: list[tuple[int, BatchItemState]],
        engine: StudioEngine,
        worker_count: int,
        progress: BatchProgress | None,
        control: BatchControl | None,
        stop_event: threading.Event | None,
        persist: Callable[..., None],
    ) -> None:
        total = len(run.items)
        remaining = iter(pending)
        futures: dict[
            Future[tuple[StudioArtifact | None, str]],
            tuple[int, BatchItemState],
        ] = {}

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="voice-batch") as executor:
            def submit_next() -> bool:
                self._check_control(control, stop_event)
                try:
                    index, item = next(remaining)
                except StopIteration:
                    return False
                self._prepare_item(item)
                future = executor.submit(
                    self._generate_item,
                    run,
                    item,
                    index,
                    total,
                    engine,
                    progress,
                    stop_event,
                )
                futures[future] = (index, item)
                return True

            for _ in range(worker_count):
                if not submit_next():
                    break

            while futures:
                self._check_control(control, stop_event)
                done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda current: futures[current][0]):
                    _, item = futures.pop(future)
                    artifact, error = future.result()
                    self._finish_item(run, item, artifact, error)
                    persist()
                    submit_next()

    @staticmethod
    def _prepare_item(item: BatchItemState) -> None:
        item.status = "running"
        item.attempts += 1
        item.error = ""

    def _generate_item(
        self,
        run: BatchRun,
        item: BatchItemState,
        index: int,
        total: int,
        engine: StudioEngine,
        progress: BatchProgress | None,
        stop_event: threading.Event | None,
    ) -> tuple[StudioArtifact | None, str]:
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        if progress:
            progress(f"Đang tạo {index + 1}/{total}: {item.spec.item_id}", index / total)
        try:
            generation_spec = run.spec.item_generation_spec(item.spec, run.root_dir)
            generation_spec.validate()
            return (
                engine.generate(
                    generation_spec,
                    lambda message: progress(message, index / total) if progress else None,
                ),
                "",
            )
        except TaskCancelledError:
            raise
        except Exception as error:
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError() from error
            return None, str(error)

    def _finish_item(
        self,
        run: BatchRun,
        item: BatchItemState,
        artifact: StudioArtifact | None,
        error: str,
    ) -> None:
        if artifact is None:
            item.status = "failed"
            item.error = error
            return
        self.repository.record_artifact(run, item, artifact)
        item.status = "done"

    @staticmethod
    def _check_control(
        control: BatchControl | None,
        stop_event: threading.Event | None,
    ) -> None:
        if control:
            control()
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()

    def _combine(self, run: BatchRun, progress: BatchProgress | None) -> None:
        if not run.spec.combine:
            return
        successful = [item for item in run.items if item.status == "done" and item.wav_path]
        if not successful:
            return
        if progress:
            progress("Đang ghép các mục thành một file...", 0.98)
        root = Path(run.root_dir).resolve()
        combined_wav = root / "combined.wav"
        try:
            concatenate_wavs([root / item.wav_path for item in successful], combined_wav, run.spec.gap_ms)
            run.combined_wav_path = combined_wav.relative_to(root).as_posix()
            if "mp3" in run.spec.formats:
                combined_mp3 = root / "combined.mp3"
                converted, message = try_convert_to_mp3(combined_wav, combined_mp3)
                if converted:
                    run.combined_mp3_path = combined_mp3.relative_to(root).as_posix()
                else:
                    run.warnings.append(message)
        except Exception as error:
            run.warnings.append(f"Không ghép được đầu ra: {error}")

    @staticmethod
    def _final_status(run: BatchRun) -> str:
        if run.completed_count == len(run.items):
            if run.spec.combine and not run.combined_wav_path:
                return "partial"
            return "completed"
        if run.completed_count:
            return "partial"
        return "failed"
