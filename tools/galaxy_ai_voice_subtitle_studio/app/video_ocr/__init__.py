"""Editor-native burned-in subtitle recognition."""

from .models import (
    OCR_ACCURATE_MODE,
    OCR_FAST_MODE,
    OcrBox,
    OcrCue,
    OcrObservation,
    VideoOcrOptions,
    VideoOcrRegion,
    VideoOcrResult,
)
from .service import (
    VideoOcrRuntime,
    default_video_ocr_runtime,
    install_video_ocr_runtime,
    recognize_burned_subtitles,
    register_video_ocr_result,
)

__all__ = [
    "OCR_ACCURATE_MODE",
    "OCR_FAST_MODE",
    "OcrBox",
    "OcrCue",
    "OcrObservation",
    "VideoOcrOptions",
    "VideoOcrRegion",
    "VideoOcrResult",
    "VideoOcrRuntime",
    "default_video_ocr_runtime",
    "install_video_ocr_runtime",
    "recognize_burned_subtitles",
    "register_video_ocr_result",
]
