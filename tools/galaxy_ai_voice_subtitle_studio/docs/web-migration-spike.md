# Pha 0 — Spike kiểm chứng web shell (pywebview + FastAPI)

Ngày: 2026-08-17. Kết quả thực nghiệm trên máy người dùng.

## Checklist

| # | Hạng mục | Kết quả |
|---|---|---|
| 1 | `pip install -r requirements-web.txt` (Python 3.12 + 3.13) | ✅ fastapi 0.141.1, uvicorn 0.52.3, pywebview 6.2.1, pythonnet 3.1.0 |
| 2 | `python run.py --web` mở cửa sổ load 127.0.0.1:3902, WS round-trip | ✅ HEALTH_OK, trang spike render, WS hoạt động (test + manual) |
| 3 | `window.create_file_dialog` FILE + FOLDER trả path thật | ⚠️ Chưa xác nhận bằng tay (cần người dùng bấm nút trong cửa sổ spike) — API pywebview 6 có sẵn, sẽ xác nhận ở Pha 1 |
| 4 | Drag-drop ngoài có `pywebviewFullPath` | ⚠️ Chưa xác nhận bằng tay — giữ nguyên fallback file-dialog |
| 5 | `debug=True` DevTools + tiếng Việt | ⚠️ Chưa kiểm bằng tay (chỉ bật ở dev mode) |
| 6 | Đóng cửa sổ → 0 process mồ côi | ✅ CLEAN_EXIT, exit 0; không có python/webview2/ffmpeg mới sau khi đóng |
| 7 | tkinter vẫn chạy | ✅ Full suite 326 passed (gồm test_gui_layout dựng GalaxyStudioApp thật) |
| 8 | Full test suite xanh | ✅ 326 passed + 1 skipped (thêm 9 test `tests/server/`) |
| + | `--serve-only` + curl | ✅ health/trang/task OK; tắt bằng Ctrl+C (hoặc Stop-Process) |

## Ghi chú kỹ thuật

- **uvicorn trong thread**: dùng `lifespan="off"` + bind loop trong WS handler — hết traceback ồn khi shutdown. `timeout_graceful_shutdown=5`, thread daemon, `should_exit`/`force_exit`.
- **Shutdown sạch**: HEALTH_OK → CLOSING → CLEAN_EXIT (driver tự đóng sau 8s), không để lại tiến trình.
- **Watchdog**: frontend ping `/api/health` mỗi 5s; không ping 60s → tự thoát (chưa kích hoạt test crash — làm ở Pha 1).
- Còn 2 tiến trình uvicorn mồ côi TỪ PHIÊN CŨ (trước dự án này) trên máy người dùng — không liên quan tới spike.

## Còn để xác nhận (Pha 1)

- File dialog + drag-drop thực tế (cần thao tác tay).
- Gõ tiếng Việt trong input.
- Watchdog crash-window test.
