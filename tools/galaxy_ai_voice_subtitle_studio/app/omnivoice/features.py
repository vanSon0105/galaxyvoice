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

# Language ids offered when the runtime's language map is unavailable.
COMMON_LANGUAGES = (
    "vi",
    "en",
    "zh",
    "ja",
    "ko",
    "th",
    "id",
    "fr",
    "de",
    "es",
    "ru",
    "auto",
)

# Voice-design attribute tables (label -> English value joined into the
# design instruction). Shared by the tkinter tab and the web studio page.
GENDER_CHOICES = {"Không chọn": "", "Nam": "male", "Nữ": "female"}
AGE_CHOICES = {
    "Không chọn": "",
    "Trẻ em": "child",
    "Thiếu niên": "teenager",
    "Thanh niên": "young adult",
    "Trung niên": "middle-aged",
    "Cao tuổi": "elderly",
}
PITCH_CHOICES = {
    "Không chọn": "",
    "Rất trầm": "very low pitch",
    "Trầm": "low pitch",
    "Trung bình": "moderate pitch",
    "Cao": "high pitch",
    "Rất cao": "very high pitch",
}
STYLE_CHOICES = {"Không chọn": "", "Thì thầm": "whisper"}
ACCENT_CHOICES = {
    "Không chọn": "",
    "Mỹ": "american accent",
    "Anh": "british accent",
    "Úc": "australian accent",
    "Canada": "canadian accent",
    "Ấn Độ": "indian accent",
    "Trung Quốc": "chinese accent",
    "Hàn Quốc": "korean accent",
    "Nhật Bản": "japanese accent",
    "Bồ Đào Nha": "portuguese accent",
    "Nga": "russian accent",
}
DIALECT_CHOICES = {
    "Không chọn": "",
    "Hà Nam": "河南话",
    "Thiểm Tây": "陕西话",
    "Tứ Xuyên": "四川话",
    "Quý Châu": "贵州话",
    "Vân Nam": "云南话",
    "Đông Bắc": "东北话",
}
