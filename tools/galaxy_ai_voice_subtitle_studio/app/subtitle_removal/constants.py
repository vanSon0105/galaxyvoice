"""UI constants owned by the subtitle-removal tab."""

from .service import (
    AI_INPAINT_MODE,
    BLUR_MODE,
    FAST_AI_INPAINT_MODE,
    FILL_MODE,
    STRIP_MODE,
)

REMOVAL_MODE_LABELS = {
    STRIP_MODE: "Bỏ track phụ đề",
    BLUR_MODE: "Làm mờ vùng phụ đề",
    FILL_MODE: "Xóa thông minh",
    AI_INPAINT_MODE: "AI ProPainter",
    FAST_AI_INPAINT_MODE: "Fast AI (tối ưu)",
}
REMOVAL_MODE_CODES = {label: code for code, label in REMOVAL_MODE_LABELS.items()}

PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 270
PREVIEW_FPS = 12
