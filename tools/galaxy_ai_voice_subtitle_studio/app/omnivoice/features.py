from __future__ import annotations

from .models import AUTO_MODE, CLONE_MODE, DESIGN_MODE


MODE_LABELS = {
    "Tự chọn giọng": AUTO_MODE,
    "Nhái giọng đã lưu": CLONE_MODE,
    "Thiết kế giọng": DESIGN_MODE,
}

NON_VERBAL_TAGS = {
    "Cười": "[laughter]",
    "Thở dài": "[sigh]",
    "Xác nhận": "[confirmation-en]",
    "Hỏi": "[question-en]",
    "Hỏi ah": "[question-ah]",
    "Hỏi oh": "[question-oh]",
    "Ngạc nhiên ah": "[surprise-ah]",
    "Ngạc nhiên oh": "[surprise-oh]",
    "Ngạc nhiên wa": "[surprise-wa]",
    "Không hài lòng": "[dissatisfaction-hnn]",
}
