# Galaxy AI Voice & Subtitle Studio

Ứng dụng desktop gọn nhẹ cho workflow:

1. Dán kịch bản.
2. Chọn Edge TTS online hoặc Windows SAPI offline.
3. Generate audio `.wav`.
4. Tự xuất phụ đề `.srt` khớp timing theo từng đoạn audio đã sinh.
5. Xuất thêm `.mp3` nếu máy có `ffmpeg`.
6. Trích audio `.wav` / `.mp3` từ video bằng `ffmpeg`.
7. Tạo phụ đề từ giọng nói trong video bằng `faster-whisper`, rồi dịch phụ đề bằng AI qua API OpenAI-compatible.
8. Tạo giọng local bằng OmniVoice với Auto Voice, nhái giọng, thiết kế giọng và thư viện profile.
9. Quản lý project lồng tiếng, Stories, Audiobook, catalog hơn 1.000 voice design và lịch sử tạo cục bộ.

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

File nằm cạnh `run.py` và được cập nhật sau khi thay đổi output folder, engine/voice, speed, volume, pause, tùy chọn export, ngôn ngữ, Whisper, thiết bị xử lý, cấu hình dựng video hoặc AI provider/model/base URL. `config.json` được Git bỏ qua để mỗi máy giữ cấu hình riêng.

API key, nội dung Script, project name và video đang chọn không được ghi vào file cấu hình. API key tiếp tục được đọc từ ô nhập hoặc biến môi trường.

App ghi log chẩn đoán dạng xoay vòng tại `%LOCALAPPDATA%\GalaxyAIStudio\logs\galaxy-studio.log`.
Log chỉ ghi trạng thái vận hành, tên tác vụ và loại lỗi; không ghi API key hay nội dung subtitle.

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

Trong GUI, `Create Subtitles` chỉ xử lý video và đưa kết quả vào ba tab `Script`, `Sub gốc`, `Sub dịch`; bước này chưa ghi file vào output folder. Có thể kiểm tra hoặc sửa nội dung SRT trong hai tab subtitle, sau đó bấm `Export Subtitles` để xuất bộ file theo đúng cấu trúc cũ. App hỏi xác nhận trước khi đóng, đổi video hoặc tạo lại nếu draft hiện tại chưa được export. CLI với `--transcribe` vẫn xử lý và xuất file ngay trong một lệnh.

App lưu cache transcription và checkpoint dịch tại `%LOCALAPPDATA%\GalaxyAIStudio\cache`. Khi chạy lại cùng video, ngôn ngữ và Whisper model, app vẫn trích audio phục vụ export nhưng bỏ qua bước Whisper đã hoàn thành. Phần dịch tiếp tục từ các cue còn thiếu sau lỗi mạng hoặc khi app bị đóng; API key không được ghi vào cache.

Batch AI trả JSON lỗi không thể phục hồi hoặc sai ngôn ngữ sẽ không được đánh dấu hoàn thành. Các batch đã dịch đúng vẫn nằm trong checkpoint; chạy lại sẽ tiếp tục phần còn thiếu thay vì xuất file subtitle trộn ngôn ngữ.

DeepSeek dịch các batch nhỏ song song và luôn ghép kết quả theo index gốc. Thanh tiến độ hiển thị số cue đã dịch, ví dụ `Translating 240/768`. Batch nào trả sai ngôn ngữ mới được chia nhỏ và chạy fallback riêng, nên các batch đúng không bị làm lại.

Mục `Thiết bị xử lý` trong tab Voice điều khiển riêng bước Whisper: `Tự động` ưu tiên NVIDIA CUDA `float16` rồi fallback CPU `int8`, `CPU (không dùng GPU)` luôn ép chạy CPU, còn `NVIDIA GPU rời` báo lỗi nếu máy không có CUDA thay vì âm thầm đổi thiết bị. Edge TTS và dịch cloud không dùng GPU cục bộ.

Bấm `Generate` sau đó sẽ tạo voice từ nội dung trong tab `Script`. Nếu script được tạo từ video và bạn đổi `Translate to` trước khi generate, app sẽ dịch script sang ngôn ngữ mới rồi mới tạo voice. Nếu máy có voice Windows/SAPI trùng ngôn ngữ đã chọn, app sẽ tự chọn voice đó; nếu không, hãy cài hoặc chọn voice phù hợp thủ công.

## Dựng video nhẹ

Tab `Dựng video` là editor một video, một audio ngoài và một track SRT, dành cho bước ghép cuối mà không cần mở CapCut. `Thêm video`, `Thêm audio` và `Thêm SRT` chỉ nhập nguồn vào Media Bin bên trái; kéo nguồn xuống timeline hoặc double-click/nhấn `Đưa vào timeline` khi muốn sử dụng. Có thể giữ nhiều nguồn trong Media Bin, còn thả nguồn mới sẽ thay track cùng loại đang dùng. Timing trong SRT được đặt thẳng lên timeline; audio được đặt tại vị trí thả. Danh sách cue cho phép sửa thời điểm bắt đầu, kết thúc và nội dung, hoặc kéo cả block và hai mép cue trực tiếp trên track Subtitle.

Preview phát video cùng audio gốc/audio ngoài và subtitle tại vị trí playhead. Hai pane workspace/timeline, đường phân cách giữa các track và mức zoom timeline đều co giãn được. `Căn theo video` chỉ dùng khi cần scale toàn bộ track subtitle để khớp chính xác đầu-cuối video; SRT có timing đúng thì không cần bấm.

Phần xuất hỗ trợ giữ độ phân giải gốc, 720p, 1080p hoặc 2K `2560x1440`, cùng FPS gốc, 24, 30, 50 hoặc 60. `Tự động` ưu tiên NVIDIA NVENC, sau đó Intel Quick Sync trên Windows và cuối cùng CPU `libx264`; nếu hardware encoder tự động bị lỗi, app thử lại bằng CPU. Audio ngoài có thể trộn với audio gốc hoặc thay hoàn toàn. Mỗi lần xuất tạo một thư mục project gồm MP4, bản SRT đã chỉnh và `editor_manifest.json`.

## Xóa phụ đề khỏi video

Tab `Xóa phụ đề` xử lý video đã có phụ đề. Preview có nút `Phát` / `Tạm dừng` và timeline để xem hoặc tua đến đúng đoạn có chữ; kéo khung vàng quanh vùng subtitle rồi chọn một trong năm chế độ:

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

## Tách giọng hát và nhạc nền

Tab `Tách âm thanh` dùng model có sẵn trong thư mục `ultimatevocalremover/models` và giao diện theo workflow UVR: chọn input/output, WAV/FLAC/MP3, process method, model, segment, overlap, thiết bị, stem đơn, sample 30 giây và preset. Input có thể là audio hoặc video; video được chuẩn bị thành stereo 44.1 kHz bằng FFmpeg bundled trước khi tách. Preset tùy chỉnh được lưu riêng trong `audio_presets.json` và không được đưa lên Git.

Engine chạy trong môi trường riêng tại `%LOCALAPPDATA%\GalaxyAIStudio\models\AudioSeparator`, không dùng chung dependency với Whisper hoặc ProPainter. Bấm nút bánh răng trong tab rồi chọn `Install / Update Engine`, hoặc chạy thủ công:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_audio_separator.ps1 -Device auto
```

`Auto` ưu tiên NVIDIA CUDA, sau đó dùng DirectML cho MDX/VR trên Intel hoặc AMD GPU. Demucs không chạy DirectML ổn định nên tự dùng CPU khi không có NVIDIA. Mỗi lần xử lý tạo thư mục project riêng, các file stem và `audio_separation_manifest.json`; nút dừng sẽ kết thúc cả cây tiến trình đang chạy.

Backend dùng [audio-separator](https://github.com/nomadkaraoke/python-audio-separator), wrapper MIT cho các model UVR. Khi phân phối sản phẩm, giữ credit cho Ultimate Vocal Remover và tác giả model theo yêu cầu của dự án nguồn.

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

## VoiceStudio đầy đủ

`omnivoice` và `omnivoicestudio` là hai lớp khác nhau. `omnivoice` là engine TTS/voice conversion Apache-2.0 được Galaxy gọi bằng worker riêng. `omnivoicestudio` là ứng dụng VoiceStudio 0.4.x hoàn chỉnh, gồm React, Tauri và FastAPI, phát hành theo AGPL-3.0-only.

Trang `Voice > VoiceStudio` nhúng trực tiếp giao diện React hoàn chỉnh vào Galaxy bằng WebView2. VoiceStudio vẫn chạy như một dịch vụ FastAPI local riêng tại `http://127.0.0.1:3900`, nên Galaxy không sửa lõi hay sao chép hàng trăm API của dự án nguồn. Các workspace `Studio`, `Dubbing`, `Stories`, `Audiobook`, `Gallery`, `Transcriptions`, `Projects` và `Settings` đều dùng chính giao diện VoiceStudio.

Cài snapshot local từ nút `Cài runtime local`, hoặc chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_voicestudio.ps1
```

Galaxy đóng băng source VoiceStudio 0.4.2, frontend production và wheel WebView trong `vendor/`. Script sao chép snapshot bất biến sang `%LOCALAPPDATA%\GalaxyAIStudio\models\VoiceStudio`, tạo Python runtime riêng từ `uv.lock` và không tải MSI hay phụ thuộc vào bản phát hành VoiceStudio mới nhất. Dependency Python vẫn cần Internet ở lần cài đầu; model chỉ được tải khi chọn trong VoiceStudio. Dữ liệu, model, cache và log nằm ngoài repo, tách khỏi runtime OmniVoice nhẹ của Galaxy.

## OmniVoice local và nhái giọng

Ngoài trang VoiceStudio đầy đủ, main tab `Voice` vẫn giữ các workflow nhẹ do Galaxy xây trên engine `omnivoice`: `Clone`, `Design`, `Dubbing`, `Stories`, `Audiobook`, `Gallery` và `Transcripts`. Đây không phải các trang được sao chép từ dự án VoiceStudio. Các công cụ kỹ thuật `Auto Voice`, `Batch`, `LoRA`, runtime và profile đã lưu nằm gọn trong `Gallery`, nên có thể dùng engine trực tiếp mà không cần chạy sidecar đầy đủ.

`Video Dubbing` dùng sub dịch đang mở hoặc SRT nhập ngoài, giữ timing từng cue, hỗ trợ speaker/profile riêng, sửa lời, tốc độ, âm lượng, tách-ghép câu, preview, QC và lưu project trước khi đưa video, voice cùng SRT sang timeline dựng video. `Stories` hỗ trợ vai theo cú pháp `Nhân vật: lời thoại`, `[voice:Tên]`, `[pause 500ms]`, `[slow]`, `[fast]` và `[spell]`; sau khi lập kế hoạch có thể sửa, sắp xếp, preview và xuất stems từng đoạn. `Audiobook` nhập TXT, Markdown, EPUB hoặc PDF, chia chương bằng heading `#`, có từ điển phát âm, override tốc độ/pause theo chương, ảnh bìa, preview chương, checkpoint chạy tiếp và xuất WAV/MP3 hoặc M4B có chapter metadata. `Transcripts` tự lưu lịch sử mỗi lần tạo sub, cho phép tìm kiếm, sao chép, mở lại và xuất riêng hoặc hàng loạt.

Voice Gallery sinh hơn 1.000 preset hợp lệ từ taxonomy gender, age, pitch, accent và dialect của OmniVoice; có tìm kiếm, nhóm mục đích, yêu thích, preview, tạo profile và lịch sử artifact. Thanh công cụ nội dung của các trang tạo voice vẫn chèn được non-verbal tag như `[laughter]`, `[sigh]`, CMU phoneme tiếng Anh và pinyin có thanh điệu tiếng Trung. `Batch` nhận mỗi dòng là một câu hoặc JSONL theo format CLI gốc (`id`, `text`, `language_id`, `speed`, `duration`). Project và lịch sử được lưu trong `omnivoice_workspaces.json` cạnh config, không lưu API key.

OmniVoice chạy trong worker riêng và giữ model trong RAM/VRAM giữa các lần Generate. Runtime, checkpoint, Hugging Face cache và profile nằm tại `%LOCALAPPDATA%\GalaxyAIStudio\models\OmniVoice`, không dùng chung Python với app chính. Cài hoặc sửa runtime bằng nút trong GUI, hoặc chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_omnivoice.ps1 -Device auto
```

`auto` ưu tiên NVIDIA CUDA rồi mới dùng CPU. Có thể chọn `xpu` cho Intel Arc đã cài PyTorch XPU; Intel Iris Xe không được coi là Arc tương thích. Model mặc định là `k2-fsa/OmniVoice`; nút `Tải model` tải checkpoint ở lần đầu và giữ worker sẵn sàng cho các lần tạo tiếp theo.

FlashInfer chỉ dùng với NVIDIA CUDA. Cài bằng nút `Cài FlashInfer` hoặc chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_omnivoice_flashinfer.ps1
```

LoRA cần một thư mục adapter có `adapter_config.json`. Có thể áp dụng adapter trực tiếp cho generation hoặc merge sang model độc lập trong tab `LoRA`; runtime cài `peft` sẵn.

Nhái giọng nhận audio mẫu hoặc profile `.pt` đã lưu. Nếu transcript mẫu để trống, worker tải Whisper để tự nhận dạng; nhập transcript đúng sẽ tránh phần tải ASR và thường cho kết quả ổn định hơn. App yêu cầu xác nhận quyền sử dụng giọng trước khi tạo profile mới. Việc mạo danh, gian lận hoặc clone giọng không được phép là bị cấm theo disclaimer của dự án OmniVoice.

## Cấu trúc code

Code được nhóm theo tab để thay đổi một workflow không phải đọc toàn bộ ứng dụng:

```text
app/
|-- common/                  # config, cache, FFmpeg, logging, process và path
|-- voice/                   # TTS, transcription, dịch AI, SRT và UI tab Voice
|-- omnivoice/               # runtime worker, profile và các workspace OmniVoice
|   `-- workspaces/          # dubbing, stories, audiobook, gallery và transcripts
|-- voicestudio/             # launcher, runtime probe và vòng đời VoiceStudio đầy đủ
|-- video_editor/            # project, preview, export và timeline tab Dựng video
|-- audio_separation/        # backend UVR/audio-separator và UI tab Tách âm thanh
|-- subtitle_removal/        # blur, ProPainter và UI tab Xóa phụ đề
|-- gui.py                   # composition root, vòng đời app và event chung
`-- cli.py                   # entry point dòng lệnh
```

Mỗi package tab có `gui.py` cho phần giao diện và module backend riêng. `app/gui.py` chỉ ghép các mixin tab, quản lý config chung, trạng thái tác vụ và đóng ứng dụng. Test backend mirror cấu trúc này dưới `tests/`; `tests/test_gui_layout.py` là bộ integration test cho ứng dụng đã ghép.

## Test

```powershell
python -m unittest discover -s .\tests
```
