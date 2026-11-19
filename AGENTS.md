# AGENTS.md — Anime Summarizer Tool

## Dự án
Web app (FastAPI + Python) tóm tắt phim anime: tải video lên → Gemini (AI) viết kịch bản lời bình (scene-by-scene) → CapCut TTS đọc lời bình → FFmpeg cắt/nối/burn phụ đề → video tóm tắt hoàn chỉnh.

## Cấu trúc thư mục
- `backend/` — mã nguồn server (FastAPI). `frontend/` — mã nguồn React/Vite; build ra `static/`.
- `frontend/src/` — code React theo feature-folder: `app/` (`App.tsx` + `layout/`: AppLayout/Sidebar/Topbar/CommandPalette/PageHeader), `features/<domain>/` (dashboard, projects, tasks, library, quick-recap, ai-studio, settings, logs, storage), `shared/` (`ui/` primitives, `hooks/`, `styles/global.css`, `lib/` = `services/`+`utils/`+`types/`+`state/`). `main.tsx` ở gốc. Import nội bộ dùng alias `@/` (khai báo ở `vite.config.ts` + `tsconfig.json`).
- `data/` — **toàn bộ dữ liệu runtime** (không commit): `db/` (SQLite), `media/` (`final|segments|audio|manual` — phục vụ qua URL `/output/...` và `/media/...`), `voice_refs/`, `chrome_profile/` (Chrome CDP), `cache/` (`preview/`, `shot/`), `logs/`, `work/` (mỗi task), `tmp/`, `uploads/`, cùng `admin_settings.json`/`gemini_models.json`.
- Entry scripts ở gốc: `run.bat`, `open_app.bat`, `stop_server.bat`, `run_silent.py`. `Voice.json` = catalog giọng CapCut (đọc bởi `config`/`capcut_tts_api`).

## Kiến trúc
- `backend/main.py` — entry point FastAPI: khởi tạo logging/DB, tạo `app`, mount `static` + `data/media` (URL `/static`, `/output`), middleware heartbeat + vòng auto-shutdown idle, hâm nóng TTS, gắn router. Chạy chính (`python -m backend.main`).
- `backend/api/` — tầng API (tách từ monolith `main.py`): `deps.py` (hạ tầng dùng chung: logger, cache ngắn hạn, heartbeat, helper tính target/options/updater tiến độ/đường dẫn nén/dọn file output), `pipeline.py` (`process_pipeline`, `_run_ai_studio_auto`), `routers/*.py` (`pages`, `system`, `manual`, `projects`, `voices`, `library`, `tasks`, `bridge`, `media`, `admin`). Toàn bộ URL & cách chạy giữ nguyên.
- `backend/core/config.py` — hằng số (API key, model, thư mục, giọng nói `VOICES`, `DETAIL_LEVELS`, `DEFAULT_VOICE`). Đường dẫn runtime suy ra từ `BASE_DIR/data` (`DATA_DIR`, `MEDIA_DIR`/`OUTPUT_DIR`, `CACHE_DIR`, `LOGS_DIR`, ...).
- `backend/core/task_manager.py` — `Task`/`TaskManager` chạy pipeline nền bằng thread, lưu tiến độ.
- `backend/core/database.py` — lưu projects/episodes/tasks/segments vào **SQLite** (`data/db/anime_summarizer.db`, schema trong `backend/core/db_engine.py` + migrat JSON cũ ở `db_migration.py`), `reset_stuck_episodes()`. Segments lưu `tts_duration`+`shot_count`; episodes/tasks lưu `target_sec`/`est_sec`/`tts_sec` (đồng bộ TIẾN TRÌNH qua `_episode_updater` để UI xem kịch bản ngay khi AI trả về, dù đang chạy). Registry nhân vật gửi AI = bảng chung + cache các tập CHƯA XÉT (cột `episodes.characters_reviewed`: NULL=tự động xét khi cache ⊆ bảng chung, 1=đã xét do bấm Lưu, 0=ép chưa xét). Thêm cột mới cho DB cũ phải qua `_ensure_column` trong `init_db`.
- `backend/core/key_pool.py` — nhiều Gemini key, round-robin, ghi ngược `.env`.
- `backend/services/gemini_service.py` — gọi Gemini API: upload video, `build_scene_prompt()`, `parse_result_text()`, `summarize_video()`.
- `backend/services/tts_service.py` — `TTSEngine` định tuyến theo `voice_type`: **voicestudio** (local HTTP API) hoặc **capcut** (cloud), `generate_all_tts()` (5 luồng cho CapCut, 2 luồng + semaphore toàn cục cho VoiceStudio), `preview_voice()` (cache đĩa, bỏ qua giọng local khi warm), `warm_voicestudio()` hút cold-start lúc khởi động.
- `backend/services/voicestudio_service.py` — VoiceStudio local (debpalash/VoiceStudio - ElevenLabs alternative, OpenAI-compatible API tại `http://127.0.0.1:3900/v1`). Hỗ trợ tổng hợp giọng nói qua `POST /v1/audio/speech`, danh sách voice/profile qua `GET /v1/audio/voices`, tạo profile qua `POST /profiles`, kiểm tra server qua `check_health()`.
- Thư viện giọng VoiceStudio & custom profiles: nạp động qua `_load_voicestudio_voices()` từ VoiceStudio API và registry. Endpoint `POST/DELETE /api/voices/custom`, `POST/DELETE /api/projects/{id}/voice-ref`. UI chọn provider + giọng ở `ConfigPanel` và quản lý ở Settings.
- `backend/services/video_service.py` — FFmpeg: nén video gửi Gemini, cắt/nối phân đoạn, burn phụ đề, `concat_videos`, `create_srt`, `detect_shots` (shot detection).
- Shot detection (`detect_shots`) có **2 backend** chọn qua `SHOT_DETECTOR='auto'|'pyscenedetect'|'ffmpeg'`: (1) PySceneDetect — histogram HSV + built-in flash merge; (2) FFmpeg `select='gt(scene,0.2)',showinfo`. `'auto'` ưu tiên PySceneDetect nếu import được, fallback FFmpeg khi lỗi. Method chọn qua `PYSCENE_METHOD='adaptive'|'content'`; cache shot có gắn detector+tham số nên đổi config là tự invalidate. Post-filter CHUNG `SHOT_MERGE_MIN` (0.5s) gộp micro-shot vào shot trước.
- `backend/services/ai_studio_bridge.py` — automation Google AI Studio qua **Playwright CDP** trên **Chrome profile RIÊNG** (dir `data/chrome_profile`, **non-default**): `_launch_automation_chrome()` (Popen, không PS), `run_ai_studio_auto()` với các bước B1–B12 + `extract_script_from_text()`. Đây là backend cho mode thủ công (replace `ai_studio_gui` — không còn dùng ở `main.py`).
- `backend/services/ai_studio_gui.py` + `backend/services/vision_matcher.py` — tự động hóa KIỂU CŨ (template matching, OpenCV/pyautogui). **ĐÃ XOÁ** cùng `omnivoice_service` (dead code, không nơi nào gọi).
- `backend/services/capcut_tts_api/` — client CapCut TTS.
- `backend/utils/srt_parser.py` — module `Segment` (dataclass) + parse/adjust/overlap timing.
- `static/` — build output của frontend: `index.html` + `assets/` (KHÔNG sửa tay), `favicon.svg`, `app_icon.ico`, `anime_summarizer_bridge.user.js`.

## Chạy / Verify
- Môi trường ảo: `venv\Scripts\python.exe` (ngay trong repo; `run.bat`/`open_app.bat`/`run_silent.py` đều dùng venv này).
- Khởi động: `venv\Scripts\python.exe -m backend.main` (hoặc `run.bat`) → http://localhost:8000.
- **Compile/typecheck backend** (bắt buộc sau mỗi thay đổi):
  `venv\Scripts\python.exe -m compileall backend`
- **JS/TS check**: `npx.cmd tsc -b` (workdir `frontend/`) và `npm.cmd run build`. `static/` là build output — KHÔNG sửa tay.
- Chưa có test framework tự động; verify bằng cách khởi động server và chạy thử pipeline thật.
- **Dữ liệu dùng chung giữa các phiên bản**: `config.DATA_DIR` lấy từ env `ANIME_DATA_DIR` (mặc định `BASE_DIR/data`); `config` cũng nạp thêm `DATA_DIR/.env` (không override `.env` cạnh code). Chạy `setup_shared_data.bat [thư-mục]` một lần để chuyển `data/` + `.env` ra ngoài repo và set biến user-level → nâng cấp bản mới chỉ thay code, KHÔNG copy `data/`. Biến chỉ có hiệu lực ở cửa sổ/terminal mới.

## Quy ước & ràng buộc quan trọng
- **TTS có 2 provider: VoiceStudio local (mặc định) + CapCut cloud — CẢ HAI CHỈ DÙNG TIẾNG VIỆT.** Không fallback chéo provider và không fallback sang Edge/gTTS. CapCut lỗi → retry tối đa 3 lần (delay tăng dần 1.5s→3s), fail thì ném lỗi rõ. VoiceStudio lỗi (server chưa bật/kết nối lỗi) → ném lỗi rõ, không tự chuyển CapCut. Không được thêm giọng/cơ chế Edge vào `VOICES`.
- **Prompt KHÔNG fix cứng số phân đoạn.** Luôn đưa KHOẢNG (`±20%` qua `build_scene_prompt`) + tổng `target_words` để AI tự quyết. Không hardcode số segment cố định.
- `GEMINI_MODEL` mặc định = `gemini-3.6-flash` (model khác có thể bị Google ngưng cho tài khoản này). Không đổi ngầm sang model không xác thực.
- Lỗi HTTP 503 "high demand" từ Gemini là **tạm thời từ server Google**, không phải lỗi code. Xử lý bằng cách giảm `max_output_tokens`/tối ưu prompt, không retry toàn bộ.
- **Nén video gửi Gemini**: mọi chức năng dùng `compress_video_for_upload(..., height=480, fps=24)`. Mode thủ công còn thêm `keep_audio=True` (AI Studio yêu cầu đính kèm file từ máy, không nhận URL).
- `edge_female` là giá trị CŨ đã bỏ — KHÔNG dùng làm default tham số. Giọng mặc định là `config.DEFAULT_VOICE = 'vs_default'` (VoiceStudio local). Không còn giọng/default Edge trong code.
- Output AI trả về tối giản: mỗi dòng `timestamp<TAB>narration` (`00:00:00,000\t...`). Backend tự suy `end_time`, `index`, `scene_description`.
- File nén mode thủ công lưu tại `data/media/manual/` (cố định, **giữ lại** — không xóa).
- **Browser automation (Playwright) = Chrome profile riêng + CDP.** Chrome 136+ CHẶN remote-debugging trên User Data MẶC ĐỊNH → không CDP được profile thật (`User Data\Profile 7`). Copy session sang dir khác hỏng login (Device Bound Sessions). Nên automation dùng **dir riêng** `data/chrome_profile` (dir non-default → CDP OK qua `subprocess.Popen` với list argv, KHÔNG qua PowerShell `Start-Process` vì nó nuốt dấu nháy/quoted path). User **đăng nhập 1 lần** trong cửa sổ automation (tự động chờ tối đa 4 phút), session còn lại sau đó. Không `--user-data-dir` = profile thật, không copy profile, không Playwright persistent_context.

## Bảo mật
- `.env` chứa `GEMINI_API_KEY` — không commit/log key. `GEMINI_API_KEY` từ env hoặc `config.GEMINI_API_KEY`.

## Skills
Các agent-skills nằm tại `.agents/skills/` (khóa bởi `skills-lock.json`, nguồn GitHub `addyosmani/agent-skills`). Dùng meta-skill `using-agent-skills` để biết skill nào áp dụng cho tác vụ hiện tại (debug → `debugging-and-error-recovery`, review → `code-review-and-quality`, API → `api-and-interface-design`, v.v.).
