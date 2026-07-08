from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import GenerationOptions, generate_package
from .tts import PowerShellSapiTTS


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.gui or _should_open_gui(args):
        from .gui import run_app

        run_app()
        return 0

    tts = PowerShellSapiTTS()
    if args.list_voices:
        for voice in tts.list_voices():
            print(voice.label)
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
    parser.add_argument("--list-voices", action="store_true", help="List Windows SAPI voices.")
    parser.add_argument("--text", help="Narration text to synthesize.")
    parser.add_argument("--text-file", help="UTF-8 text file to synthesize.")
    parser.add_argument("--output-dir", default="exports", help="Directory where exports are written.")
    parser.add_argument("--name", help="Project/export name.")
    parser.add_argument("--voice", help="Exact Windows SAPI voice name.")
    parser.add_argument("--rate", type=int, default=0, choices=range(-10, 11), metavar="-10..10")
    parser.add_argument("--volume", type=int, default=100, choices=range(0, 101), metavar="0..100")
    parser.add_argument("--pause-ms", type=int, default=250)
    parser.add_argument("--max-chars", type=int, default=160)
    parser.add_argument("--no-mp3", action="store_true", help="Skip optional MP3 export.")
    parser.add_argument("--clean-segments", action="store_true", help="Delete per-cue segment WAV files.")
    return parser


def _should_open_gui(args: argparse.Namespace) -> bool:
    return not any([args.list_voices, args.text, args.text_file])


def _read_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    raise SystemExit("Provide --text, --text-file, --list-voices, or --gui.")
