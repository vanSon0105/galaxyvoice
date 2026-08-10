from __future__ import annotations

import contextlib
import gc
import json
import sys
import traceback
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 1
_model: Any | None = None
_model_identity: tuple[str, str] | None = None


def _send(request_id: str, message_type: str, payload: dict[str, Any]) -> None:
    target = sys.__stdout__
    target.write(
        json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": message_type,
                "payload": payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    target.flush()


def _progress(request_id: str, message: str) -> None:
    _send(request_id, "progress", {"message": message})


def _resolve_device(torch: Any, selected: str) -> str:
    selected = str(selected or "auto").lower()
    if selected == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA không khả dụng trong OmniVoice runtime.")
        return "cuda:0"
    if selected == "xpu":
        if not hasattr(torch, "xpu") or not torch.xpu.is_available():
            raise RuntimeError("Intel XPU không khả dụng trong OmniVoice runtime.")
        return "xpu:0"
    if selected == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        return "cuda:0"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu:0"
    return "cpu"


def _load_model(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _model, _model_identity
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from omnivoice import OmniVoice

        model_id = str(payload.get("model_id") or "k2-fsa/OmniVoice")
        device = _resolve_device(torch, str(payload.get("device") or "auto"))
        identity = (model_id, device)
        if _model is not None and _model_identity == identity:
            return {"model_id": model_id, "device": device, "cached": True}
        _unload_model()
        _progress(request_id, f"Đang tải model {model_id} trên {device}...")
        dtype = (
            torch.float16
            if device.startswith(("cuda", "xpu"))
            else torch.float32
        )
        _model = OmniVoice.from_pretrained(model_id, device_map=device, dtype=dtype)
        _model_identity = identity
        return {
            "model_id": model_id,
            "device": device,
            "cached": False,
            "sampling_rate": int(_model.sampling_rate),
        }


def _unload_model() -> None:
    global _model, _model_identity
    model = _model
    _model = None
    _model_identity = None
    if model is not None:
        del model
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            torch.xpu.empty_cache()
    except (ImportError, RuntimeError):
        pass


def _generate(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    model_info = _load_model(request_id, payload)
    assert _model is not None
    with contextlib.redirect_stdout(sys.stderr):
        import soundfile as sf
        from omnivoice import VoiceClonePrompt

        mode = str(payload.get("mode") or "auto")
        language = str(payload.get("language") or "auto")
        kwargs: dict[str, Any] = {
            "text": str(payload.get("text") or ""),
            "language": None if language == "auto" else language,
            "num_step": int(payload.get("num_step") or 32),
            "guidance_scale": float(payload.get("guidance_scale", 2.0)),
            "t_shift": float(payload.get("t_shift", 0.1)),
            "layer_penalty_factor": float(payload.get("layer_penalty_factor", 5.0)),
            "position_temperature": float(payload.get("position_temperature", 5.0)),
            "class_temperature": float(payload.get("class_temperature", 0.0)),
            "speed": float(payload.get("speed", 1.0)),
            "denoise": bool(payload.get("denoise", True)),
            "normalize_text": bool(payload.get("normalize_text", False)),
            "preprocess_prompt": bool(payload.get("preprocess_prompt", True)),
            "postprocess_output": bool(payload.get("postprocess_output", True)),
            "audio_chunk_duration": float(payload.get("audio_chunk_duration", 15.0)),
            "audio_chunk_threshold": float(payload.get("audio_chunk_threshold", 30.0)),
            "pad_duration": float(payload.get("pad_duration", 0.1)),
            "fade_duration": float(payload.get("fade_duration", 0.1)),
        }
        duration = payload.get("duration")
        if duration is not None:
            kwargs["duration"] = float(duration)

        if mode == "clone":
            profile_path = str(payload.get("profile_path") or "")
            if profile_path:
                _progress(request_id, "Đang nạp profile giọng...")
                kwargs["voice_clone_prompt"] = VoiceClonePrompt.load(profile_path)
            else:
                ref_audio = str(payload.get("ref_audio") or "")
                if not ref_audio:
                    raise ValueError("Nhái giọng cần audio mẫu.")
                _progress(request_id, "Đang mã hóa giọng mẫu...")
                ref_text = str(payload.get("ref_text") or "").strip() or None
                prompt = _model.create_voice_clone_prompt(
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    preprocess_prompt=bool(payload.get("preprocess_prompt", True)),
                )
                save_profile_path = str(payload.get("save_profile_path") or "")
                if save_profile_path:
                    Path(save_profile_path).parent.mkdir(parents=True, exist_ok=True)
                    prompt.save(save_profile_path)
                kwargs["voice_clone_prompt"] = prompt
        elif mode == "design":
            kwargs["instruct"] = str(payload.get("instruct") or "")

        _progress(request_id, "Đang tổng hợp giọng nói...")
        audio = _model.generate(**kwargs)
        output_path = Path(str(payload["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _progress(request_id, "Đang lưu file WAV...")
        sf.write(output_path, audio[0], _model.sampling_rate)
        return {
            **model_info,
            "output_path": str(output_path),
            "sample_rate": int(_model.sampling_rate),
        }


def _dispatch(request_id: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command == "ping":
        return {"ready": True, "model_loaded": _model is not None}
    if command == "probe":
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            import omnivoice

        return {
            "ready": True,
            "omnivoice_version": str(getattr(omnivoice, "__version__", "unknown")),
            "torch_version": str(torch.__version__),
            "cuda": bool(torch.cuda.is_available()),
            "xpu": bool(hasattr(torch, "xpu") and torch.xpu.is_available()),
        }
    if command == "load":
        return _load_model(request_id, payload)
    if command == "unload":
        _unload_model()
        return {"unloaded": True}
    if command == "generate":
        return _generate(request_id, payload)
    if command == "languages":
        _load_model(request_id, payload)
        assert _model is not None
        return {"languages": sorted(_model.supported_language_names())}
    if command == "shutdown":
        _unload_model()
        return {"shutdown": True}
    raise ValueError(f"Lệnh OmniVoice không được hỗ trợ: {command}")


def main() -> None:
    for raw in sys.stdin:
        request_id = ""
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("Protocol message must be an object.")
            if message.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("Unsupported protocol version.")
            request_id = str(message.get("request_id") or "")
            command = str(message.get("type") or "")
            payload = message.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            result = _dispatch(request_id, command, payload)
            _send(request_id, "result", result)
            if command == "shutdown":
                return
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            _send(request_id, "error", {"message": f"{type(error).__name__}: {error}"})


if __name__ == "__main__":
    main()
