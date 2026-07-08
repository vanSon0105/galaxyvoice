# Galaxy AI Voice & Subtitle Studio

MVP local cho workflow:

1. Dán kịch bản.
2. Chọn voice Windows SAPI có sẵn trên máy.
3. Generate audio `.wav`.
4. Tự xuất phụ đề `.srt` khớp timing theo từng đoạn audio đã sinh.
5. Xuất thêm `.mp3` nếu máy có `ffmpeg`.

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

## Ghi chú về voice clone

Voice clone chưa được bật trong MVP này. Phần đó nên làm thành engine riêng sau khi chọn model/license rõ ràng, có kiểm soát quyền sử dụng giọng, và có UI quản lý sample voice. Core hiện đã tách `tts.py` để sau này thêm engine khác mà không phải viết lại GUI/SRT.

## Test

```powershell
python -m unittest discover -s .\tests
```
