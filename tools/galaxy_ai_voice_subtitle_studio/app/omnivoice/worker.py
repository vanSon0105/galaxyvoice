from __future__ import annotations

import contextlib
import gc
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 1
_model: Any | None = None
_model_identity: tuple[str, str, str, bool, bool] | None = None


def _finalize_generated_audio(
    audio: Any,
    sample_rate: int,
    *,
    trim_edges: bool,
    pad_duration: float,
    fade_duration: float,
    silence_threshold_db: float = -50.0,
) -> Any:
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    samples = np.asarray(audio, dtype=np.float32).squeeze()
    if samples.ndim != 1:
        raise ValueError(f"OmniVoice output must be mono, got shape {samples.shape}.")
    if samples.size == 0:
        return samples

    if trim_edges:
        threshold = 10.0 ** (silence_threshold_db / 20.0)
        active = np.flatnonzero(np.abs(samples) > threshold)
        if active.size:
            samples = samples[int(active[0]) : int(active[-1]) + 1]

    fade_samples = min(
        max(0, int(round(fade_duration * sample_rate))),
        samples.size // 2,
    )
    if fade_samples:
        samples = samples.copy()
        samples[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        samples[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)

    pad_samples = max(0, int(round(pad_duration * sample_rate)))
    if pad_samples:
        samples = np.pad(samples, (pad_samples, pad_samples))
    return samples


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
        lora_adapter = str(payload.get("lora_adapter") or "").strip()
        enable_flashinfer = bool(payload.get("enable_flashinfer", False))
        flashinfer_cuda_graph = bool(payload.get("flashinfer_cuda_graph", True))
        identity = (
            model_id,
            device,
            lora_adapter,
            enable_flashinfer,
            flashinfer_cuda_graph,
        )
        if _model is not None and _model_identity == identity:
            return _model_info(
                model_id,
                device,
                cached=True,
                lora_adapter=lora_adapter,
                enable_flashinfer=enable_flashinfer,
                flashinfer_cuda_graph=flashinfer_cuda_graph,
            )
        if enable_flashinfer and not device.startswith("cuda"):
            raise RuntimeError("FlashInfer chỉ hỗ trợ NVIDIA CUDA.")
        if lora_adapter and not (Path(lora_adapter) / "adapter_config.json").is_file():
            raise FileNotFoundError(f"LoRA adapter không hợp lệ: {lora_adapter}")
        _unload_model()
        _progress(request_id, f"Đang tải model {model_id} trên {device}...")
        dtype = (
            torch.float16
            if device.startswith(("cuda", "xpu"))
            else torch.float32
        )
        try:
            _model = OmniVoice.from_pretrained(model_id, device_map=device, dtype=dtype)
            if lora_adapter:
                _progress(request_id, "Đang nạp LoRA adapter...")
                from omnivoice.utils.lora import load_lora_adapter

                _model = load_lora_adapter(_model, lora_adapter)
            if enable_flashinfer:
                _progress(request_id, "Đang bật FlashInfer...")
                from omnivoice.models.omnivoice_flashinfer import apply_flashinfer

                apply_flashinfer(_model, enable_cuda_graph=flashinfer_cuda_graph)
        except Exception:
            _unload_model()
            raise
        _model_identity = identity
        return _model_info(
            model_id,
            device,
            cached=False,
            lora_adapter=lora_adapter,
            enable_flashinfer=enable_flashinfer,
            flashinfer_cuda_graph=flashinfer_cuda_graph,
        )


def _model_info(
    model_id: str,
    device: str,
    *,
    cached: bool,
    lora_adapter: str,
    enable_flashinfer: bool,
    flashinfer_cuda_graph: bool,
) -> dict[str, Any]:
    assert _model is not None
    return {
        "model_id": model_id,
        "device": device,
        "cached": cached,
        "sampling_rate": int(_model.sampling_rate),
        "languages": sorted(_model.supported_language_ids()),
        "lora_adapter": lora_adapter,
        "flashinfer": enable_flashinfer,
        "flashinfer_cuda_graph": enable_flashinfer and flashinfer_cuda_graph,
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
        postprocess_output = bool(payload.get("postprocess_output", True))
        pad_duration = max(0.0, float(payload.get("pad_duration", 0.0)))
        fade_duration = max(0.0, float(payload.get("fade_duration", 0.02)))
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
            "postprocess_output": postprocess_output,
            "audio_chunk_duration": float(payload.get("audio_chunk_duration", 15.0)),
            "audio_chunk_threshold": float(payload.get("audio_chunk_threshold", 30.0)),
            # Apply edge padding and fades ourselves so trimming has predictable results.
            "pad_duration": 0.0,
            "fade_duration": 0.0,
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
        instruct = str(payload.get("instruct") or "").strip()
        if instruct:
            kwargs["instruct"] = instruct

        _progress(request_id, "Đang tổng hợp giọng nói...")
        audio = _model.generate(**kwargs)
        output_path = Path(str(payload["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _progress(request_id, "Đang lưu file WAV...")
        finalized_audio = _finalize_generated_audio(
            audio[0],
            int(_model.sampling_rate),
            trim_edges=postprocess_output,
            pad_duration=pad_duration,
            fade_duration=fade_duration,
        )
        sf.write(output_path, finalized_audio, _model.sampling_rate)
        return {
            **model_info,
            "output_path": str(output_path),
            "sample_rate": int(_model.sampling_rate),
        }


def _merge_lora(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _model, _model_identity
    base_model = str(payload.get("base_model") or "").strip()
    adapter = Path(str(payload.get("lora_adapter") or "")).expanduser()
    output_dir = Path(str(payload.get("output_dir") or "")).expanduser()
    if not base_model:
        raise ValueError("Hãy chọn base model để merge LoRA.")
    if not (adapter / "adapter_config.json").is_file():
        raise FileNotFoundError(f"LoRA adapter không hợp lệ: {adapter}")
    _validate_empty_output_dir(output_dir)

    _unload_model()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staged_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.merge-", dir=output_dir.parent)
    )
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            from transformers import AutoTokenizer

            from omnivoice.models.omnivoice import OmniVoice, _resolve_model_path
            from omnivoice.utils.lora import load_lora_adapter

            _progress(request_id, "Đang tải base model để merge LoRA...")
            model = OmniVoice.from_pretrained(base_model, train=True, dtype=torch.float32)
            _progress(request_id, "Đang merge LoRA adapter...")
            merged = load_lora_adapter(model, str(adapter), merge=True)
            merged.save_pretrained(staged_dir)

            tokenizer_source = (
                str(adapter)
                if (adapter / "tokenizer_config.json").is_file()
                else base_model
            )
            tokenizer = AutoTokenizer.from_pretrained(tokenizer_source)
            tokenizer.save_pretrained(staged_dir)
            resolved_base = Path(_resolve_model_path(base_model))
            for name in ("audio_tokenizer", "chat_template.jinja"):
                source = resolved_base / name
                target = staged_dir / name
                if source.is_dir() and not target.exists():
                    shutil.copytree(source, target)
                elif source.is_file() and not target.exists():
                    shutil.copy2(source, target)
            del merged
            del model
        _validate_empty_output_dir(output_dir)
        if output_dir.exists():
            output_dir.rmdir()
        staged_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    gc.collect()
    _model = None
    _model_identity = None
    return {"output_dir": str(output_dir), "base_model": base_model, "adapter": str(adapter)}


def _validate_empty_output_dir(path: Path) -> None:
    if path.is_file():
        raise NotADirectoryError(f"Output LoRA phải là một thư mục: {path}")
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Thư mục output LoRA phải rỗng: {path}")


def _dispatch(request_id: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command == "ping":
        return {"ready": True, "model_loaded": _model is not None}
    if command == "probe":
        with contextlib.redirect_stdout(sys.stderr):
            import importlib.util
            import torch
            import omnivoice

        return {
            "ready": True,
            "omnivoice_version": str(getattr(omnivoice, "__version__", "unknown")),
            "torch_version": str(torch.__version__),
            "cuda": bool(torch.cuda.is_available()),
            "xpu": bool(hasattr(torch, "xpu") and torch.xpu.is_available()),
            "flashinfer": bool(importlib.util.find_spec("flashinfer")),
            "peft": bool(importlib.util.find_spec("peft")),
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
    if command == "merge_lora":
        return _merge_lora(request_id, payload)
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
