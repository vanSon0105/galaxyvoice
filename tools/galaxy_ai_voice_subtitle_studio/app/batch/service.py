from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from ..common.errors import TaskCancelledError
from ..studio.service import StudioEngine
from ..voice.audio import concatenate_wavs, try_convert_to_mp3
from .models import BatchRun
from .repository import BatchRepository


BatchProgress = Callable[[str, float], None]
BatchCheckpoint = Callable[[dict[str, object]], None]
BatchControl = Callable[[], None]


class BatchService:
    def __init__(self, repository: BatchRepository) -> None:
        self.repository = repository

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
        if engine.engine_id != run.spec.engine_id:
            raise ValueError(f"Adapter {engine.engine_id} không xử lý được Batch {run.spec.engine_id}.")
        run.status = "running"
        run.task_id = task_id
        self.repository.save(run)
        total = len(run.items)

        try:
            for index, item in enumerate(run.items):
                if item.status == "done" or item.status == "failed":
                    continue
                if control:
                    control()
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledError()
                item.status = "running"
                item.attempts += 1
                item.error = ""
                self.repository.save(run)
                if progress:
                    progress(f"Đang tạo {index + 1}/{total}: {item.spec.item_id}", index / total)
                try:
                    generation_spec = run.spec.item_generation_spec(item.spec, run.root_dir)
                    generation_spec.validate()
                    artifact = engine.generate(
                        generation_spec,
                        lambda message: progress(message, index / total) if progress else None,
                    )
                except TaskCancelledError:
                    item.status = "pending"
                    self.repository.save(run)
                    raise
                except Exception as error:
                    if stop_event is not None and stop_event.is_set():
                        item.status = "pending"
                        self.repository.save(run)
                        raise TaskCancelledError() from error
                    item.status = "failed"
                    item.error = str(error)
                else:
                    self.repository.record_artifact(run, item, artifact)
                    item.status = "done"
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

            self._combine(run, progress)
            run.status = self._final_status(run)
            self.repository.save(run)
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
            self.repository.save(run)
            raise
        except Exception:
            run.status = "interrupted"
            for item in run.items:
                if item.status == "running":
                    item.status = "pending"
            self.repository.save(run)
            raise

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
