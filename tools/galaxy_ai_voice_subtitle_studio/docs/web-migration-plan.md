# Kế hoạch di cư Galaxy sang kiến trúc web (pywebview + FastAPI + React)

> Cập nhật: 2026-08-21. Pha 0–6 đã hoàn thành; Pha 7–8 còn lại.
> File này là bản kế hoạch chi tiết cho toàn bộ quá trình di cư.

## 1. Bối cảnh & quyết định đã chốt

Galaxy AI Voice & Subtitle Studio là app desktop tkinter (~22k dòng Python, 7 workspace). Vấn đề: tkinter chạm trần về thẩm mỹ và hiệu năng (đã chứng minh qua sự cố image-element làm đơ app 3–11s mỗi tab — commit `9ceca01`).

Mục tiêu: đưa giao diện đạt chất lượng OmniVoiceStudio (webapp React render bằng WebView2/GPU), **khi web ổn định thì bỏ hẳn tkinter**. Ưu tiên hiệu quả/ổn định hơn tốc độ.

Quyết định kiến trúc (đã duyệt):

| Mục | Quyết định |
|---|---|
| Shell desktop | **pywebview 6** (cửa sổ WebView2 độc lập, không Tk, BSD-3) |
| Backend | **FastAPI + uvicorn trong thread cùng process**, port 3902, chỉ loopback |
| Frontend | **React + TypeScript + Vite + Tailwind v4** — code tự viết, học theo design language (không copy AGPL của omnivoicestudio) |
| Realtime | **1 WebSocket** `/ws/events` (sự kiện + progress + task status), cancel qua HTTP |
| Task | `TaskRegistry` server-side: task_id, status, `stop_event`, `on_cancel` hook |
| Config | Chung `config.json` (AppConfig v6) — hai UI dùng cùng dataclass, không lệch nhau |
| Nguyên tắc | **Migration contract**: router chỉ là lớp trình bày mỏng; mọi fix nằm ở service dùng chung; service API đóng băng, chỉ thêm field |

Cấu trúc:

```
app/server/               # FastAPI backend
  main.py  shell.py  event_bus.py  tasks.py  ws.py  files.py
  routers/{tasks,settings,voice,omnivoice,omnivoice_workspaces}.py
frontend/                 # React + TS + Vite + Tailwind (dist/ được commit)
app/<domain>/*            # Service thuần — tái sử dụng nguyên vẹn cho cả 2 UI
app/gui.py + app/*/gui.py # tkinter — sẽ xóa ở Pha 8
```

Lệnh chạy: `python run.py` (tkinter, mặc định hiện tại) · `python run.py --web` (web) · `--serve-only` · `--web-dev-url` (dev + debug).

## 2. Tiến độ đã hoàn thành

| Pha | Nội dung | Commit |
|---|---|---|
| 0 | Foundation spike: server, WS, task, shutdown sạch (0 mồ côi) | `2aedf7e` |
| 1 | Frontend foundation: shell 7 tab, tokens, Settings | (cùng trên) |
| 2 | Video Dubbing: generate/extract/transcribe/draft/export + fix ffmpeg timeout/cancel/dọn rác | `fe538e1`, `8e536df`, `ebeb209`, `08ee9fa` |
| 3a | OmniVoice Studio/Profiles/Batch + fix Stop-lost/stderr queue/profile guard | `99e79dc` |
| 3b+3c | Workspaces: repository, gallery, transcripts, document editor, dubbing, render + resume | `f64464a` |
| 4 | VoiceStudio iframe: tự khởi động, install/launch single-flight, shutdown sạch | `f91dd32`, `64714bd` |
| 5 | Tách âm thanh UVR: workspace web, preset/runtime cache, cancel theo task | `feat(P5)` |
| 6 | Xóa phụ đề: 5 mode, worker ProPainter dài hạn, preview và cancel | `feat(P6)` |

## 3. Pha 4 đã hoàn thành và các pha còn lại

### Pha 4 — VoiceStudio iframe ✅

**Mục tiêu**: tab VoiceStudio trong web = nhúng SPA vendored qua `<iframe src="http://127.0.0.1:3900">`. Cơ chế WebView2-profile của tkinter (disk leak) mất hoàn toàn; backend mồ côi được dọn khi shutdown.

- Backend `app/server/routers/voicestudio.py`:
  - `GET /api/voicestudio/status` → `inspect_runtime(probe_backend=False)` (file checks nhẹ)
  - `POST /api/voicestudio/launch` → tái sử dụng `VoiceStudioController.launch()` + `wait_until_ready` (single-flight, generation counter — fix race install/launch cũ)
  - `POST /api/voicestudio/install` → task chạy installer (progress từ log file, single-flight)
  - `POST /api/voicestudio/stop`
- `shell.py:shutdown()`: thêm `voicestudio_controller.stop_all()` (dọn backend 3900 mồ côi — bài học từ máy người dùng có 2 uvicorn mồ côi)
- Frontend: `VoiceStudioPage.tsx` — state machine (chưa cài → cài với progress → sẵn sàng) → iframe; tab đã có sẵn trong nav
- Lưu ý: iframe cross-origin → không inject được `VOICESTUDIO_THEME_SCRIPT`; SPA vendored có dark theme sẵn cùng bộ màu — chấp nhận, ghi README
- **DoD**: iframe chạy; install có progress; attach backend đang chạy; đóng app → không còn backend 3900 mồ côi; tests voicestudio service vẫn xanh

### Pha 5 — Tách âm thanh ✅

**Mục tiêu**: workspace Tách âm thanh (UVR) + fix 3 lỗi High quan trọng nhất về tiến trình.

- Backend `app/server/routers/audio_separation.py`:
  - `GET /api/audio/meta` (methods/devices/formats), `GET /api/audio/models` (cache), `GET/POST /api/audio/presets` (chung `audio_presets.json`)
  - `POST /api/audio/separate` → task + cancel (`stop_event` đã có sẵn trong service)
- **Fix service**:
  - **Task-scoped process groups** (quan trọng nhất): mở rộng `ManagedProcessRegistry` cho phép đăng ký process theo task; cancel chỉ kill cây của task đó — hết lỗi `terminate_all` giết nhầm task tab khác. Áp dụng cho audio separation trước, các module khác hưởng theo sau
  - Probe runtime (`nvidia-smi`, venv import torch) rời request handler + cache 60s — hết đơ UI
  - Bounded stderr drain
- Frontend: `SeparationPage.tsx` — method/model/device/format/segment/overlap, presets, sample mode
- **DoD**: tách được cả 2 method; cancel giữa chừng; chạy song song với 1 task voice → không task nào bị giết nhầm; tests xanh

### Pha 6 — Xóa phụ đề ✅

**Mục tiêu**: Xóa phụ đề (ProPainter) + fix các lỗi hiệu năng lớn.

- Backend `app/server/routers/subtitle_removal.py`:
  - `GET /api/removal/modes`, `POST /api/removal/remove` (task + cancel), `POST /api/removal/preview` (frame tại t), region model
- **Fix service**:
  - **1 worker ProPainter dài hạn cho cả job** (hiện mỗi chunk spawn lại → 270 lần load model cho video 90 phút) — respawn chỉ khi device/params đổi
  - blur/fill: đúng container/codec thay vì ép `.mp4` + `-c:a copy` (hết lỗi muxer với nguồn PCM/DTS)
  - Cancel thật sự; log forwarding giới hạn; cửa sổ CUDA-OOM detection rộng hơn
- Frontend: `RemovalPage.tsx` — `<video>` preview, kéo vùng phụ đề bằng pointer events, license accept
- **DoD**: cả 5 chế độ chạy; model load 1 lần/job (log-verified); cancel; preview scrub; tests xanh

### Pha 7 — Dựng video

**Mục tiêu**: timeline editor trên web — khó nhất về UI.

- Backend `app/server/routers/video_editor.py`:
  - `POST /api/editor/load` (probe → EditorMediaInfo), `POST /api/editor/cues` (parse SRT), `POST /api/editor/export` (task + cancel), still/preview qua `files.py`
- **Fix service**: validate audio offset ≥ duration (hết xuất câm im lặng); stderr drain; task-scoped kill
- Frontend:
  - `src/components/timeline/geometry.ts` — module thuần (hit-test, snap, px↔ms) port ngữ nghĩa `timeline.py`, test vitest
  - `Timeline.tsx` — SVG: ruler, clip, track cue, playhead, kéo/thả
  - `EditorPage.tsx` — media bin, bảng cue, track audio (volume/offset), export modal
  - Playback bằng `<video>` element — bỏ cả hệ ffplay frame-rendering của tkinter
- **DoD**: seek, kéo clip, sửa cue, preview, export mix/replace với mọi encoder/resolution; không fail im lặng; vitest geometry xanh

### Pha 8 — Gỡ tkinter (sau sign-off của người dùng)

1. Xóa toàn bộ file GUI tkinter (danh sách đầy đủ ở §5)
2. `app/common/theme.py` → `app/common/palette.py` (AppPalette thuần, không tkinter) + test assert hex khớp `frontend/src/styles/tokens.css`
3. `--web` thành mặc định; `--tk` giữ tạm đến khi sign-off xong
4. Xóa phần tkwry/WebViewProfileLease khỏi `app/voicestudio/runtime.py`
5. `Galaxy Studio.bat`: cài `requirements-web.txt` lần đầu → `run.py --web`
6. Test: xóa/điều chỉnh đúng 4 file tkinter (`test_gui_layout.py`, `omnivoice/test_gui.py`, `common/test_theme.py` → palette-token, `video_editor/test_timeline.py` → vitest geometry)
7. README + AGENTS.md + ghi chú ranh giới AGPL
8. **DoD**: 0 import tkinter trong `app/`; `python run.py` mở web; CLI nguyên; test xanh; git sạch; review độc lập cuối cùng

## 4. Checklist 14 lỗi High từ review (trạng thái)

| # | Lỗi | Pha fix | Trạng thái |
|---|---|---|---|
| 1 | ffmpeg không timeout/registry; thiếu cancel; folder rác | P2 | ✅ |
| 2 | OmniVoice Stop mất tác dụng | P3a | ✅ |
| 3 | stderr queue không giới hạn | P3a | ✅ |
| 4 | discard_pending_profile xóa profile đã lưu | P3a | ✅ |
| 5 | batch không check cancel | P3a | ✅ |
| 6 | project-id mixup giữa modes | P3b | ✅ |
| 7 | scan resumable chặn UI | P3b | ✅ (endpoint riêng, không chặn UI web) |
| 8 | WebView2 recovery profile leak | P4 | ✅ (mất theo thiết kế iframe) |
| 9 | race install/launch thế hệ cũ | P4 | ✅ |
| 10 | backend mồ côi khi đóng app | P4 | ✅ |
| 11 | terminate_all giết nhầm task khác | P5 | ✅ |
| 12 | probe nvidia-smi/venv trên UI thread | P5 | ✅ |
| 13 | ProPainter spawn mỗi chunk | P6 | ✅ |
| 14 | blur/fill muxer `-c:a copy` | P6 | ✅ |
| 15 | audio offset ≥ duration xuất câm | P7 | ⏳ |
| 16 | installer ffmpeg không checksum; pin faster-whisper | độc lập | ✅ (hoàn thành cùng P5) |

## 5. Testing

- **Service layer**: `py -3.13 -m pytest tests/` — phải xanh cuối MỌI pha (trừ 4 file tkinter xử lý ở Pha 8)
- **API mới**: `tests/server/` per router, TestClient + monkeypatch service (không TTS/ffmpeg/whisper thật)
- **Frontend**: `cd frontend && npm test` (vitest) + `npm run build` (dist commit)
- **Smoke thật**: `python run.py --serve-only` + curl, hoặc mở cửa sổ 10s tự đóng (verify CLEAN_EXIT + 0 process mồ côi)
- **Parity**: mỗi workspace — tkinter là oracle so sánh, người dùng sign-off trước khi xóa tab tương ứng

## 6. Rủi ro & giảm thiểu (tóm tắt)

| Rủi ro | Giảm thiểu |
|---|---|
| pywebview cần main thread | uvicorn daemon thread, `lifespan="off"`, không đụng window từ server code |
| uvicorn treo khi shutdown trong thread | `should_exit`, chờ graceful 5s rồi mới `force_exit`; watchdog: frontend ping health 5s, 60s không ping → tự thoát + dọn tiến trình |
| Process mồ côi | shutdown() duy nhất; đã verify 0 mồ côi ở P0; task-scoped groups ở P5 |
| Port đụng VoiceStudio 3900 | Galaxy dùng 3902 (env override), retry 3902→3912 |
| Ranh giới AGPL | Toàn bộ code tự viết; VoiceStudio ở process riêng sau iframe |
| Hai UI lệch nhau | Migration contract; chung file data (config.json, omnivoice_workspaces.json, audio_presets.json) |

## 7. Danh sách file GUI tkinter sẽ xóa (Pha 8)

```
app/gui.py
app/voice/gui.py
app/omnivoice/gui.py
app/omnivoice/advanced_gui.py
app/omnivoice/workspaces/gui.py
app/omnivoice/workspaces/common/editor_gui.py
app/omnivoice/workspaces/stories/gui.py
app/omnivoice/workspaces/audiobook/gui.py
app/omnivoice/workspaces/dubbing/gui.py
app/subtitle_removal/gui.py
app/audio_separation/gui.py
app/video_editor/gui.py
app/video_editor/timeline.py
app/video_editor/media_bin.py
app/common/theme.py  →  thay bằng app/common/palette.py
app/voicestudio/gui.py
```

## 8. Lệnh thường dùng

```powershell
# App web (mặc định từ Pha 8; hiện tại: --web)
python run.py --web
python run.py --serve-only            # server không cửa sổ (Vite dev proxy)
python run.py --web --web-dev-url http://localhost:5173

# Test
py -3.13 -m pytest tests -q           # Python (357+ tests)
cd frontend; npm test; npm run build  # Frontend

# Dev frontend
cd frontend; npm run dev              # Vite 5173 → proxy /api+/ws → 3902
```
