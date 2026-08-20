from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import traceback
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    print("GALAXY_JSON:" + json.dumps(payload, ensure_ascii=True), flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    return parser.parse_args()


class _ModelCache:
    def __init__(self, repo_dir: Path) -> None:
        os.chdir(repo_dir)
        sys.path.insert(0, str(repo_dir))

        from model.modules import flow_comp_raft
        from model import propainter as propainter_model
        from model import recurrent_flow_completion
        from utils import download_util

        self._flow_module = flow_comp_raft
        self._completion_module = recurrent_flow_completion
        self._inpaint_module = propainter_model
        self._download_module = download_util
        self._raft_factory = flow_comp_raft.RAFT_bi
        self._completion_factory = recurrent_flow_completion.RecurrentFlowCompleteNet
        self._inpaint_factory = propainter_model.InpaintGenerator
        self._download = download_util.load_file_from_url
        self._raft: Any = None
        self._completion: Any = None
        self._inpaint: Any = None
        self._weights: dict[tuple[Any, ...], Any] = {}
        self.models_loaded = False

        flow_comp_raft.RAFT_bi = self._cached_raft
        recurrent_flow_completion.RecurrentFlowCompleteNet = self._cached_completion
        propainter_model.InpaintGenerator = self._cached_inpaint
        download_util.load_file_from_url = self._cached_download

    def _cached_download(self, *args: Any, **kwargs: Any) -> Any:
        key = (kwargs.get("url", args[0] if args else None), kwargs.get("model_dir"))
        if key not in self._weights:
            self._weights[key] = self._download(*args, **kwargs)
        return self._weights[key]

    def _cached_raft(self, *args: Any, **kwargs: Any) -> Any:
        if self._raft is None:
            self._raft = self._raft_factory(*args, **kwargs)
        return self._raft

    def _cached_completion(self, *args: Any, **kwargs: Any) -> Any:
        if self._completion is None:
            self._completion = self._completion_factory(*args, **kwargs)
        return self._completion

    def _cached_inpaint(self, *args: Any, **kwargs: Any) -> Any:
        if self._inpaint is None:
            self._inpaint = self._inpaint_factory(*args, **kwargs)
            self.models_loaded = True
        return self._inpaint


def _request_argv(script: Path, payload: dict[str, Any]) -> list[str]:
    argv = [
        str(script),
        "--video",
        str(payload["video"]),
        "--mask",
        str(payload["mask"]),
        "--output",
        str(payload["output"]),
        "--subvideo_length",
        str(payload["subvideo_length"]),
        "--neighbor_length",
        str(payload["neighbor_length"]),
        "--ref_stride",
        str(payload["ref_stride"]),
    ]
    resize_ratio = float(payload.get("resize_ratio", 1.0))
    if resize_ratio < 1.0:
        argv.extend(("--resize_ratio", f"{max(0.25, resize_ratio):.2f}"))
    if payload.get("fp16"):
        argv.append("--fp16")
    return argv


def main() -> int:
    args = _parse_args()
    repo_dir = Path(args.repo).resolve()
    script = repo_dir / "inference_propainter.py"
    cache = _ModelCache(repo_dir)
    _emit({"event": "ready"})

    for raw_line in sys.stdin:
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        request_id = str(payload.get("id") or "")
        if payload.get("command") == "shutdown":
            _emit({"event": "stopped", "id": request_id})
            return 0
        if payload.get("command") != "process":
            _emit({"event": "error", "id": request_id, "error": "Unknown worker command."})
            continue

        first_load = not cache.models_loaded
        old_argv = sys.argv
        try:
            sys.argv = _request_argv(script, payload)
            runpy.run_path(str(script), run_name="__main__")
            result = Path(payload["output"]) / Path(payload["video"]).stem / "inpaint_out.mp4"
            _emit(
                {
                    "event": "result",
                    "id": request_id,
                    "path": str(result),
                    "models_loaded": first_load and cache.models_loaded,
                }
            )
        except BaseException as error:
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            _emit(
                {
                    "event": "error",
                    "id": request_id,
                    "error": f"{type(error).__name__}: {error}",
                    "traceback": traceback.format_exc(limit=12),
                }
            )
        finally:
            sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
