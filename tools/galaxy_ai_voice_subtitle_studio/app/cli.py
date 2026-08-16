from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common.diagnostics import configure_logging
from .voice.engine import GenerationOptions, generate_package
from .voice.media import MediaExtractionOptions, extract_audio_from_video
from .voice.transcription import VideoSubtitleOptions, create_subtitles_from_video
from .voice.translator import default_translation_provider, translation_provider_codes
from .voice.tts import EDGE_ENGINE_CODE, create_tts_engine, tts_engine_codes


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.serve_only:
        from .server.shell import run_web_app

        return run_web_app(port=args.web_port, serve_only=True)

    if args.gui or _should_open_gui(args):
        if args.web:
            from .server.shell import run_web_app

            return run_web_app(
                port=args.web_port,
                dev_url=args.web_dev_url or None,
                debug=bool(args.web_dev_url),
            )

        from .gui import run_app

        run_app()
        return 0

    tts = create_tts_engine(args.tts_engine)
    if args.list_voices:
        for voice in tts.list_voices():
            print(voice.label)
        return 0

    if args.video:
        if args.text or args.text_file:
            parser.error("--video cannot be combined with --text or --text-file.")
        if args.transcribe:
            result = create_subtitles_from_video(
                VideoSubtitleOptions(
                    video_path=Path(args.video),
                    output_dir=Path(args.output_dir),
                    project_name=args.name or "",
                    source_language=args.source_language,
                    target_language="none" if args.no_translate else args.target_language,
                    whisper_model=args.whisper_model,
                    ai_provider=args.ai_provider,
                    ai_model=args.ai_model,
                    ai_base_url=args.ai_base_url,
                    ai_api_key=args.ai_api_key,
                ),
                progress=lambda message: print(message),
            )
            print(f"Audio: {result.audio_path}")
            print(f"Original SRT: {result.source_srt_path}")
            if result.translated_srt_path:
                print(f"Translated SRT: {result.translated_srt_path}")
            print(f"Manifest: {result.manifest_path}")
            for warning in result.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            return 0

        result = extract_audio_from_video(
            MediaExtractionOptions(
                video_path=Path(args.video),
                output_dir=Path(args.output_dir),
                project_name=args.name or "",
                export_wav=not args.no_wav,
                export_mp3=not args.no_mp3,
            ),
            progress=lambda message: print(message),
        )
        if result.wav_path:
            print(f"WAV: {result.wav_path}")
        if result.mp3_path:
            print(f"MP3: {result.mp3_path}")
        print(f"Manifest: {result.manifest_path}")
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        return 0

    text = _read_text(args)
    options = GenerationOptions(
        text=text,
        output_dir=Path(args.output_dir),
        project_name=args.name or "",
        voice_name=args.voice or None,
        rate=args.rate,
        volume=args.volume,
        pause_ms=args.pause_ms,
        max_chars=args.max_chars,
        export_mp3=not args.no_mp3,
        keep_segments=not args.clean_segments,
    )
    result = generate_package(options, tts=tts, progress=lambda message: print(message))
    print(f"WAV: {result.wav_path}")
    print(f"SRT: {result.srt_path}")
    if result.mp3_path:
        print(f"MP3: {result.mp3_path}")
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Galaxy AI Voice & Subtitle Studio")
    parser.add_argument("--gui", action="store_true", help="Open the desktop UI.")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Open the web (pywebview) desktop UI instead of tkinter.",
    )
    parser.add_argument(
        "--serve-only",
        action="store_true",
        help="Run only the web server without a window (Vite dev proxy target).",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=3902,
        help="Port for the web server (default 3902).",
    )
    parser.add_argument(
        "--web-dev-url",
        default="",
        help="Frontend dev server URL for the web window (enables debug mode).",
    )
    parser.add_argument("--list-voices", action="store_true", help="List voices for the selected TTS engine.")
    parser.add_argument(
        "--tts-engine",
        default=EDGE_ENGINE_CODE,
        choices=tts_engine_codes(),
        help="Voice engine: edge (online, default) or sapi (Windows offline).",
    )
    parser.add_argument("--text", help="Narration text to synthesize.")
    parser.add_argument("--text-file", help="UTF-8 text file to synthesize.")
    parser.add_argument("--video", help="Video file to extract audio from.")
    parser.add_argument("--transcribe", action="store_true", help="Create SRT subtitles from --video.")
    parser.add_argument("--output-dir", default="exports", help="Directory where exports are written.")
    parser.add_argument("--name", help="Project/export name.")
    parser.add_argument("--voice", help="Exact voice name for the selected TTS engine.")
    parser.add_argument("--rate", type=int, default=0, choices=range(-10, 11), metavar="-10..10")
    parser.add_argument("--volume", type=int, default=100, choices=range(0, 101), metavar="0..100")
    parser.add_argument("--pause-ms", type=int, default=250)
    parser.add_argument("--max-chars", type=int, default=160)
    parser.add_argument("--no-wav", action="store_true", help="Skip WAV export when extracting from video.")
    parser.add_argument("--no-mp3", action="store_true", help="Skip optional MP3 export.")
    parser.add_argument("--clean-segments", action="store_true", help="Delete per-cue segment WAV files.")
    parser.add_argument("--source-language", default="auto", help="Video language code, or auto.")
    parser.add_argument("--target-language", default="vi", help="Translation language code.")
    parser.add_argument("--no-translate", action="store_true", help="Only create the original-language SRT.")
    parser.add_argument("--whisper-model", default="base", help="faster-whisper model size.")
    parser.add_argument(
        "--ai-provider",
        default=default_translation_provider(),
        choices=translation_provider_codes(),
        help="AI translation provider.",
    )
    parser.add_argument("--ai-model", default="", help="AI translation model. Defaults to the selected provider.")
    parser.add_argument(
        "--ai-base-url",
        default="",
        help="OpenAI-compatible API base URL. Defaults to the selected provider.",
    )
    parser.add_argument("--ai-api-key", default="", help="AI translation API key; env vars are also supported.")
    return parser


def _should_open_gui(args: argparse.Namespace) -> bool:
    return not any([args.list_voices, args.text, args.text_file, args.video])


def _read_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    raise SystemExit("Provide --text, --text-file, --video, --list-voices, or --gui.")
