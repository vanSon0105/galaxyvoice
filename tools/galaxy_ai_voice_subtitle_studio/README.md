# Galaxy AI Voice & Subtitle Studio

MVP local cho workflow:

1. Dán kịch bản.
2. Chọn voice Windows SAPI có sẵn trên máy.
3. Generate audio `.wav`.
4. Tự xuất phụ đề `.srt` khớp timing theo từng đoạn audio đã sinh.
5. Xuất thêm `.mp3` nếu máy có `ffmpeg`.
6. Trích audio `.wav` / `.mp3` từ video bằng `ffmpeg`.
7. Tạo phụ đề từ giọng nói trong video bằng `faster-whisper`, rồi dịch phụ đề bằng AI qua API OpenAI-compatible.

Bản này không dùng cloud API, không cần key, và được đặt trong `tools/` đúng yêu cầu.

## Chạy GUI

Double-click:

```text
Galaxy Studio.bat
```

Hoặc chạy bằng terminal:

```powershell
cd tools\galaxy_ai_voice_subtitle_studio
python run.py
```

## Tạo shortcut ngoài Desktop

```powershell
powershell -ExecutionPolicy Bypass -File .\install_desktop_shortcut.ps1
```

## Cài ffmpeg bundled

Video/audio workflow cần `ffmpeg`. Chạy lệnh này một lần để tải `ffmpeg.exe` vào `bin/` của tool:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_ffmpeg.ps1
```

Sau khi cài, app sẽ ưu tiên dùng:

```text
bin/ffmpeg.exe
```

Nếu file này không có, app mới tìm `ffmpeg` trong PATH.

## Chạy CLI

Liệt kê voice:

```powershell
python run.py --list-voices
```

Generate từ file text:

```powershell
python run.py --text-file .\script.txt --output-dir .\exports --name review-phim
```

Chọn voice cụ thể:

```powershell
python run.py --text-file .\script.txt --voice "Microsoft David Desktop" --rate 1 --pause-ms 300
```

Trích audio từ video:

```powershell
python run.py --video .\video.mp4 --output-dir .\exports --name review-phim
```

Chỉ xuất WAV từ video:

```powershell
python run.py --video .\video.mp4 --no-mp3
```

Tạo SRT gốc và SRT dịch tiếng Việt từ video:

```powershell
python run.py --video .\video.mp4 --transcribe --source-language en --target-language vi --output-dir .\exports --name review-phim
```

Chỉ tạo SRT gốc, không dịch:

```powershell
python run.py --video .\video.mp4 --transcribe --source-language auto --no-translate
```

## Output

Mỗi lần generate tạo một thư mục riêng:

```text
exports/
`-- galaxy_project/
    |-- galaxy_project.wav
    |-- galaxy_project.srt
    |-- galaxy_project.mp3
    |-- manifest.json
    `-- segments/
        |-- segment_001.wav
        `-- segment_002.wav
```

Nếu không có `ffmpeg`, tool vẫn xuất `.wav` và `.srt`, chỉ bỏ qua `.mp3`.

Khi trích audio từ video, `ffmpeg` là bắt buộc. Tool ưu tiên bản bundled trong `bin/ffmpeg.exe`, nên người dùng không cần cài ffmpeg toàn hệ thống. WAV được xuất dạng mono 16 kHz PCM để sẵn sàng cho bước speech-to-text/Whisper.

## Video sang subtitle và dịch AI

Cài phần nhận giọng nói:

```powershell
pip install -r .\requirements-transcription.txt
```

Cấu hình API dịch AI bằng biến môi trường, hoặc nhập trực tiếp trong GUI:

```powershell
$env:OPENAI_API_KEY="sk-..."
$env:GALAXY_TRANSLATION_MODEL="gpt-4o-mini"
$env:GALAXY_TRANSLATION_BASE_URL="https://api.openai.com/v1"
```

`GALAXY_TRANSLATION_BASE_URL` dùng endpoint tương thích OpenAI `/v1/chat/completions`, nên có thể đổi sang provider khác nếu muốn. Nếu chọn `No translation`, app chỉ tạo SRT gốc từ video.

## Ghi chú về voice clone

Voice clone chưa được bật trong MVP này. Phần đó nên làm thành engine riêng sau khi chọn model/license rõ ràng, có kiểm soát quyền sử dụng giọng, và có UI quản lý sample voice. Core hiện đã tách `tts.py` để sau này thêm engine khác mà không phải viết lại GUI/SRT.

## Test

```powershell
python -m unittest discover -s .\tests
```
