from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.config import AppConfig, load_app_config, save_app_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_config_round_trip_preserves_user_preferences(self) -> None:
        config = AppConfig(
            output_dir=r"D:\Videos\Galaxy",
            tts_engine="sapi",
            voice_name="Vietnamese Voice",
            rate=3,
            volume=85,
            pause_ms=400,
            max_chars=180,
            export_mp3=False,
            keep_segments=False,
            video_export_wav=True,
            video_export_mp3=False,
            video_source_language="en",
            video_target_language="vi",
            whisper_model="small",
            voice_processing_device="cpu",
            ai_provider="deepseek",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://api.deepseek.com",
            subtitle_removal_mode="fill",
            subtitle_region_x=8,
            subtitle_region_y=70,
            subtitle_region_width=84,
            subtitle_region_height=22,
            subtitle_blur_strength=24,
            removal_processing_device="cuda",
            propainter_license_accepted=True,
            audio_output_dir=r"D:\Videos\Separated",
            audio_process_method="vr",
            audio_model_name="1_HP-UVR.pth",
            audio_output_format="FLAC",
            audio_segment_size="320",
            audio_overlap="10",
            audio_processing_device="directml",
            audio_gpu_conversion=True,
            audio_vocals_only=True,
            audio_instrumental_only=False,
            audio_sample_mode=True,
            audio_saved_setting="Vocal extraction",
            editor_output_dir=r"D:\Videos\Edited",
            editor_resolution="2k",
            editor_fps="60",
            editor_encoder="nvidia",
            editor_audio_mode="replace",
            editor_source_volume=75,
            editor_external_volume=125,
            editor_subtitle_font_size=30,
            editor_subtitle_margin=54,
            editor_timeline_zoom=0.25,
            omnivoice_output_dir=r"D:\Videos\OmniVoice",
            omnivoice_model_id="local/omnivoice",
            omnivoice_device="cuda",
            omnivoice_language="vi",
            omnivoice_num_step=16,
            omnivoice_guidance_scale=1.8,
            omnivoice_t_shift=0.2,
            omnivoice_layer_penalty_factor=4.5,
            omnivoice_position_temperature=3.0,
            omnivoice_class_temperature=0.4,
            omnivoice_speed=1.15,
            omnivoice_duration=12.5,
            omnivoice_normalize_text=True,
            omnivoice_audio_chunk_duration=12.0,
            omnivoice_audio_chunk_threshold=24.0,
            omnivoice_pad_duration=0.2,
            omnivoice_fade_duration=0.15,
            omnivoice_profile_id="narrator",
            omnivoice_clone_instruct="Vietnamese accent",
            omnivoice_batch_mode="clone",
            omnivoice_long_form_mode="design",
            omnivoice_long_form_gap_ms=400,
            omnivoice_enable_flashinfer=True,
            omnivoice_flashinfer_cuda_graph=False,
            omnivoice_lora_adapter=r"D:\Models\adapter",
            omnivoice_design_gender="female",
            omnivoice_design_pitch="low pitch",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_app_config(config, path)

            self.assertEqual(load_app_config(path), config)

    def test_invalid_config_values_fall_back_or_are_clamped(self) -> None:
        payload = {
            "tts_engine": "unknown",
            "rate": 999,
            "volume": -5,
            "pause_ms": "bad",
            "max_chars": 9999,
            "export_mp3": "yes",
            "subtitle_removal_mode": "unknown",
            "subtitle_region_x": -20,
            "subtitle_region_y": 200,
            "subtitle_region_width": 0,
            "subtitle_region_height": 500,
            "subtitle_blur_strength": 999,
            "voice_processing_device": "intel",
            "removal_processing_device": "amd",
            "audio_process_method": "unknown",
            "audio_output_format": "AAC",
            "audio_processing_device": "metal",
            "editor_resolution": "8k",
            "editor_fps": "120",
            "editor_encoder": "other",
            "editor_audio_mode": "duck",
            "editor_source_volume": 999,
            "editor_timeline_zoom": -1,
            "omnivoice_device": "iris",
            "omnivoice_num_step": 999,
            "omnivoice_guidance_scale": -2,
            "omnivoice_speed": 9,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_app_config(path)

        self.assertEqual(config.tts_engine, "edge")
        self.assertEqual(config.rate, 10)
        self.assertEqual(config.volume, 0)
        self.assertEqual(config.pause_ms, 250)
        self.assertEqual(config.max_chars, 260)
        self.assertTrue(config.export_mp3)
        self.assertEqual(config.subtitle_removal_mode, "blur")
        self.assertEqual(config.subtitle_region_x, 0)
        self.assertEqual(config.subtitle_region_y, 99)
        self.assertEqual(config.subtitle_region_width, 1)
        self.assertEqual(config.subtitle_region_height, 1)
        self.assertEqual(config.subtitle_blur_strength, 100)
        self.assertEqual(config.voice_processing_device, "auto")
        self.assertEqual(config.removal_processing_device, "auto")
        self.assertEqual(config.audio_process_method, "mdx")
        self.assertEqual(config.audio_output_format, "WAV")
        self.assertEqual(config.audio_processing_device, "auto")
        self.assertEqual(config.editor_resolution, "original")
        self.assertEqual(config.editor_fps, "source")
        self.assertEqual(config.editor_encoder, "auto")
        self.assertEqual(config.editor_audio_mode, "mix")
        self.assertEqual(config.editor_source_volume, 200)
        self.assertEqual(config.editor_timeline_zoom, 0.1)
        self.assertEqual(config.omnivoice_device, "auto")
        self.assertEqual(config.omnivoice_num_step, 64)
        self.assertEqual(config.omnivoice_guidance_scale, 0.0)
        self.assertEqual(config.omnivoice_speed, 1.5)

    def test_fast_ai_removal_mode_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"subtitle_removal_mode": "fast_ai_inpaint"}),
                encoding="utf-8",
            )

            config = load_app_config(path)

        self.assertEqual(config.subtitle_removal_mode, "fast_ai_inpaint")

    def test_broken_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_invalid_utf8_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_bytes(b'\xff{"output_dir": "exports"}')

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_valid_json_with_wrong_shape_is_preserved_as_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("[]", encoding="utf-8")

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_read_os_error_is_reported_to_the_caller(self) -> None:
        path = Path("config.json")
        with patch.object(Path, "read_text", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                load_app_config(path)

    def test_api_key_is_never_written_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"output_dir": "exports", "ai_api_key": "secret-key"}),
                encoding="utf-8",
            )
            config = load_app_config(path)
            save_app_config(config, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("ai_api_key", saved)


if __name__ == "__main__":
    unittest.main()
