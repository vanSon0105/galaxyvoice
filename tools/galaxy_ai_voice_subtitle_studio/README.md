# Galaxy AI Voice & Subtitle Studio

MVP desktop cho workflow:

1. Dán kịch bản.
2. Chọn Edge TTS online hoặc Windows SAPI offline.
3. Generate audio `.wav`.
4. Tự xuất phụ đề `.srt` khớp timing theo từng đoạn audio đã sinh.
5. Xuất thêm `.mp3` nếu máy có `ffmpeg`.
6. Trích audio `.wav` / `.mp3` từ video bằng `ffmpeg`.
7. Tạo phụ đề từ giọng nói trong video bằng `faster-whisper`, rồi dịch phụ đề bằng AI qua API OpenAI-compatible.

Edge TTS dùng dịch vụ giọng đọc online của Microsoft Edge nhưng không cần API key. Windows SAPI vẫn hoạt động hoàn toàn offline. Phần dịch phụ đề chỉ gọi cloud khi người dùng chọn dịch bằng OpenAI hoặc DeepSeek.

## Chạy GUI

Double-click:

```text
Galaxy Studio.bat
```

Launcher sẽ tự cài `edge-tts` ở lần mở đầu tiên nếu máy chưa có.

Hoặc chạy bằng terminal:

```powershell
cd tools\galaxy_ai_voice_subtitle_studio
pip install -r .\requirements-voice.txt
python run.py
```

## Giọng đọc

Engine mặc định là `Edge TTS (Online)`. App ưu tiên hai giọng tiếng Việt:

- Nữ: `vi-VN-HoaiMyNeural`
- Nam: `vi-VN-NamMinhNeural`

Edge TTS cần Internet và dùng `ffmpeg` bundled để chuyển audio sang WAV cho bước ghép phụ đề. Chọn `Windows SAPI (Offline)` trong GUI khi cần chạy không có mạng.

## Cấu hình tự động

App tự đọc và lưu cấu hình người dùng tại:

```text
config.json
```

File nằm cạnh `run.py` và được cập nhật sau khi thay đổi output folder, engine/voice, speed, volume, pause, tùy chọn export, ngôn ngữ, Whisper, thiết bị xử lý hoặc AI provider/model/base URL. `config.json` được Git bỏ qua để mỗi máy giữ cấu hình riêng.

API key, nội dung Script, project name và video đang chọn không được ghi vào file cấu hình. API key tiếp tục được đọc từ ô nhập hoặc biến môi trường.

## Tạo shortcut ngoài Desktop

```powershell
powershell -ExecutionPolicy Bypass -File .\install_desktop_shortcut.ps1
```

## Cài ffmpeg bundled

Video/audio workflow cần bộ FFmpeg. Chạy lệnh này một lần để tải `ffmpeg.exe`, `ffprobe.exe` và `ffplay.exe` vào `bin/` của tool:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_ffmpeg.ps1
```

Sau khi cài, app sẽ ưu tiên dùng:

```text
bin/ffmpeg.exe
bin/ffprobe.exe
bin/ffplay.exe
```

Nếu các file này không có, app tìm công cụ tương ứng trong PATH. Video preview vẫn chạy hình khi thiếu `ffplay`, nhưng sẽ không có tiếng.

## Chạy CLI

Liệt kê voice:

```powershell
python run.py --list-voices
```

Liệt kê voice Windows offline:

```powershell
python run.py --tts-engine sapi --list-voices
```

Generate từ file text:

```powershell
python run.py --text-file .\script.txt --output-dir .\exports --name review-phim
```

Chọn voice cụ thể:

```powershell
python run.py --text-file .\script.txt --voice "vi-VN-HoaiMyNeural" --rate 1 --pause-ms 300
```

Generate bằng Windows SAPI offline:

```powershell
python run.py --tts-engine sapi --text-file .\script.txt --voice "Microsoft David Desktop"
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

Trong GUI, `Create Subtitles` chỉ xử lý video và đưa kết quả vào ba tab `Script`, `Sub gốc`, `Sub dịch`; bước này chưa ghi file vào output folder. Có thể kiểm tra hoặc sửa nội dung SRT trong hai tab subtitle, sau đó bấm `Export Subtitles` để xuất bộ file theo đúng cấu trúc cũ. CLI với `--transcribe` vẫn xử lý và xuất file ngay trong một lệnh.

App lưu cache transcription và checkpoint dịch tại `%LOCALAPPDATA%\GalaxyAIStudio\cache`. Khi chạy lại cùng video, ngôn ngữ và Whisper model, app vẫn trích audio phục vụ export nhưng bỏ qua bước Whisper đã hoàn thành. Phần dịch tiếp tục từ các cue còn thiếu sau lỗi mạng hoặc khi app bị đóng; API key không được ghi vào cache.

DeepSeek dịch các batch nhỏ song song và luôn ghép kết quả theo index gốc. Thanh tiến độ hiển thị số cue đã dịch, ví dụ `Translating 240/768`. Batch nào trả sai ngôn ngữ mới được chia nhỏ và chạy fallback riêng, nên các batch đúng không bị làm lại.

Mục `Thiết bị xử lý` trong tab Voice điều khiển riêng bước Whisper: `Tự động` ưu tiên NVIDIA CUDA `float16` rồi fallback CPU `int8`, `CPU (không dùng GPU)` luôn ép chạy CPU, còn `NVIDIA GPU rời` báo lỗi nếu máy không có CUDA thay vì âm thầm đổi thiết bị. Edge TTS và dịch cloud không dùng GPU cục bộ.

Bấm `Generate` sau đó sẽ tạo voice từ nội dung trong tab `Script`. Nếu script được tạo từ video và bạn đổi `Translate to` trước khi generate, app sẽ dịch script sang ngôn ngữ mới rồi mới tạo voice. Nếu máy có voice Windows/SAPI trùng ngôn ngữ đã chọn, app sẽ tự chọn voice đó; nếu không, hãy cài hoặc chọn voice phù hợp thủ công.

## Xóa phụ đề khỏi video

GUI có hai tab chính: `Voice` giữ nguyên toàn bộ workflow tạo voice/subtitle, còn `Xóa phụ đề` xử lý video đã có phụ đề. Preview có nút `Phát` / `Tạm dừng` và timeline để xem hoặc tua đến đúng đoạn có chữ; kéo khung vàng quanh vùng subtitle rồi chọn một trong năm chế độ:

- `Bỏ track phụ đề`: loại bỏ subtitle stream rời và copy các stream còn lại, không encode lại.
- `Làm mờ vùng phụ đề`: làm mờ vùng đã chọn, phù hợp với nền chuyển động và cho kết quả ổn định.
- `Xóa thông minh`: dùng `ffprobe` để đọc kích thước video và bộ lọc `delogo` của FFmpeg để nội suy vùng đã chọn từ các pixel xung quanh. Nền đơn giản thường đẹp hơn làm mờ, nhưng có thể để lại vệt trên mặt người hoặc cảnh chuyển động mạnh.
- `AI ProPainter`: xử lý vùng subtitle cùng một dải ngữ cảnh ở chất lượng cao, dùng liên kết theo thời gian giữa nhiều frame để dựng lại nền, rồi chỉ ghép vùng đã làm sạch vào video gốc.
- `Fast AI (tối ưu)`: thu hẹp dải ngữ cảnh và giới hạn input AI ở `640x320`; nhanh hơn, tốn ít VRAM hơn và vẫn giữ nguyên độ phân giải của video ngoài vùng subtitle.

Bốn chế độ xử lý phụ đề dính vào hình xuất video MP4 H.264 và giữ audio. Mỗi lần xử lý tạo thư mục project riêng, video có hậu tố `_no_subtitles` và file `subtitle_removal_manifest.json` ghi lại chế độ, vùng chọn và thiết bị. Chế độ, vùng chọn, độ mờ và hai lựa chọn thiết bị được lưu vào `config.json`; video đang chọn và API key vẫn không được lưu.

ProPainter là engine tùy chọn. Chọn `AI ProPainter` hoặc `Fast AI (tối ưu)`, chọn `Tự động`, `CPU (không dùng GPU)` hoặc `NVIDIA GPU rời`, rồi bấm `Cài ProPainter`. Lựa chọn thiết bị trong tab xóa phụ đề chỉ áp dụng cho hai chế độ AI; ba chế độ FFmpeg còn lại không dùng GPU. Intel/AMD iGPU không chạy được CUDA của ProPainter chính thức nên phải chọn CPU. Bộ cài tạo môi trường Python riêng tại `%LOCALAPPDATA%\GalaxyAIStudio\models\ProPainter`; weights chính thức tự tải ở lần chạy AI đầu tiên. Có thể chạy bộ cài thủ công:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_propainter.ps1 -AcceptNonCommercialLicense -Device auto
```

App crop dải subtitle có thêm ngữ cảnh, chuẩn hóa dải này về CFR và giới hạn input chất lượng cao tối đa ở `960x540`. Trước khi inpaint, app phát hiện chữ, viền và bóng đổ theo từng frame để ProPainter chỉ xóa đúng các pixel subtitle thay vì che kín cả dải nền. Video dài được chia thành các đoạn có overlap; Fast AI dùng 30 giây khi còn khoảng 12 GB VRAM, 20 giây ở mức 8 GB và 15 giây ở mức 6 GB. Sau khi inpaint, FFmpeg phóng dải kết quả về đúng kích thước, feather nhẹ đường biên và chỉ ghép hình chữ nhật subtitle vào video gốc. Session AI dùng lại kết quả dò CUDA/VRAM giữa các đoạn để tránh lặp bước khởi tạo phần cứng. Vì vậy độ phân giải và nội dung ngoài vùng được chọn không bị thay bằng bản AI đã thu nhỏ. Khi đóng app, tiến trình ProPainter đang chạy cũng được dừng.

Khi chạy CUDA, app tự đọc VRAM còn trống của card, chừa thêm 512 MB dự phòng, luôn bật FP16 và chọn `subvideo_length` phù hợp. Card khoảng 12 GB dùng mức thận trọng hơn cho AI chất lượng và có thể dùng batch dài hơn ở Fast AI nhờ input nhỏ; card 6-8 GB tự giảm batch, số frame ngữ cảnh, kích thước xử lý và độ dài outer chunk. Nếu CUDA vẫn báo hết bộ nhớ, chunk hiện tại được thử lại một lần bằng profile nhỏ nhất và input thu tiếp xuống 75%; các chunk sau tiếp tục dùng mức thấp. Nếu runtime CUDA chưa được cài đúng, `Tự động` fallback CPU còn lựa chọn `NVIDIA GPU rời` sẽ báo lỗi rõ ràng.

ProPainter chính thức yêu cầu PyTorch và khuyến nghị CUDA; cấu hình tiết kiệm bộ nhớ vẫn cần khoảng 6-7 GB VRAM cho video 640x480 và khoảng 7-8 GB cho 720x480 ở FP16. CPU chạy được nhưng có thể rất chậm với video dài. Quan trọng: code và model ProPainter chỉ được cấp phép cho **mục đích phi thương mại** theo [NTU S-Lab License 1.0](https://github.com/sczhou/ProPainter/blob/main/LICENSE); không dùng chế độ này cho nội dung thương mại nếu chưa có giấy phép riêng từ tác giả. Xem [hướng dẫn và mức VRAM chính thức](https://github.com/sczhou/ProPainter#memory-efficient-inference).

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

DeepSeek:

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
$env:GALAXY_TRANSLATION_PROVIDER="deepseek"
$env:GALAXY_DEEPSEEK_MODEL="deepseek-v4-flash"
$env:GALAXY_DEEPSEEK_BASE_URL="https://api.deepseek.com"
```

CLI cũng có thể chọn trực tiếp:

```powershell
python run.py --video .\video.mp4 --transcribe --source-language en --target-language vi --ai-provider deepseek
```

Trên Windows, app cũng đọc `OPENAI_API_KEY` và `DEEPSEEK_API_KEY` từ User/Machine Environment được tạo bằng `setx`, kể cả khi biến đó chưa có trong terminal hiện tại.

`GALAXY_TRANSLATION_BASE_URL` dùng endpoint tương thích OpenAI `/v1/chat/completions`, nên có thể đổi sang provider khác nếu muốn. Nếu chọn `No translation`, app chỉ tạo SRT gốc từ video.

## Ghi chú về voice clone

Voice clone chưa được bật trong MVP này. Phần đó nên làm thành engine riêng sau khi chọn model/license rõ ràng, có kiểm soát quyền sử dụng giọng, và có UI quản lý sample voice. Core hiện đã tách `tts.py` để sau này thêm engine khác mà không phải viết lại GUI/SRT.

## Test

```powershell
python -m unittest discover -s .\tests
```
