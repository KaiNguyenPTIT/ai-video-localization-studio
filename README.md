# AI Video Localization Studio

Biến một video dài thành **video tóm tắt có lời bình + giọng đọc + phụ đề**, tự động, end-to-end.

Người dùng tải lên một tập phim / video dài. Hệ thống dùng Gemini để "xem" video và viết kịch bản
lời bình theo từng cảnh, tổng hợp giọng nói tiếng Việt, rồi dùng FFmpeg dựng lại thành một video
hoàn chỉnh có nhịp cắt khớp với lời bình.

> Đây là bản public của một công cụ mình dùng để sản xuất nội dung tóm tắt phim.
> Toàn bộ pipeline chạy local/on-prem, không phụ thuộc dịch vụ dựng video bên thứ ba.

---

## Kiến trúc

```
                    ┌──────────────────────────────────────────────┐
  Upload video ───► │  Task Manager (thread pool + progress store) │
                    └───────────────┬──────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐         ┌──────────────────┐        ┌─────────────────┐
│ Shot detection│         │  Gemini (vision) │        │   TTS engine    │
│ PySceneDetect │         │  script per scene│        │ VoiceStudio(local)
│  / FFmpeg     │         │  + character reg.│        │ / CapCut (cloud)│
└───────┬───────┘         └────────┬─────────┘        └────────┬────────┘
        │                          │                           │
        └──────────────┬───────────┴───────────────────────────┘
                       ▼
            ┌─────────────────────────┐
            │  Smart-shot editor      │  khớp timestamp lời bình ↔ shot
            │  (edit plan generator)  │  zoom / speed / flip / reverse
            └────────────┬────────────┘
                         ▼
            ┌─────────────────────────┐
            │  FFmpeg render          │  cut → concat → mix audio → xuất .srt
            │  (NVENC, 1080p30)       │
            └────────────┬────────────┘
                         ▼
                  video thành phẩm
```

## Tính năng chính

**Xử lý video**
- Phát hiện cảnh (shot detection) với 2 backend: **PySceneDetect** (histogram HSV, adaptive/content)
  và **FFmpeg scene score** — tự fallback khi backend kia lỗi.
- Cache shot theo detector + tham số, tự invalidate khi đổi cấu hình.
- Dựng video theo "smart shot": chọn shot gần timestamp lời bình nhất, thêm zoom/speed/flip/reverse
  để nhịp cắt không nhàm chán, có kiểm soát để không lệch tiếng.

**AI**
- Gemini đa phương thức: đọc trực tiếp video (nén 480p trước khi upload), sinh kịch bản theo cảnh.
- Prompt trả về **khoảng** độ dài (target ±20%), để model tự quyết số phân đoạn thay vì hardcode.
- Character registry: giữ tên nhân vật nhất quán giữa các tập.
- Key pool: nhiều API key, xoay vòng round-robin, ghi trạng thái lỗi ngược lại `.env`.

**Giọng nói**
- 2 provider, **chỉ tiếng Việt**: VoiceStudio (local, OpenAI-compatible API) và CapCut (cloud).
- Không fallback chéo provider — lỗi thì báo lỗi, tránh âm thanh lẫn nhiều nguồn.
- Hỗ trợ custom voice profile và voice reference theo từng project.

**Kỹ thuật**
- FastAPI + React 19/Vite/TypeScript, tách feature-folder.
- SQLite + migration tự động (`_ensure_column`) cho DB cũ.
- Task chạy nền, tiến trình cập nhật realtime, auto-shutdown khi idle.
- Kiểm soát song song theo **loại tài nguyên**: network (Gemini/TTS) và CPU/GPU (FFmpeg) có
  semaphore riêng, tránh nghẽn cổ chai.
- Cấu hình runtime qua `/admin` panel, áp dụng không cần restart.

## Tech stack

| Layer | Công nghệ |
|---|---|
| Backend | Python, FastAPI, SQLite, threading |
| AI | Gemini (multimodal), prompt engineering, key pooling |
| Media | FFmpeg, ffprobe, PySceneDetect, OpenCV, NVENC |
| TTS | VoiceStudio (local), CapCut TTS API |
| Frontend | React 19, TypeScript, Vite, Tailwind |

## Chạy thử

```bash
# 1. Môi trường
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 2. Cấu hình
copy .env.example .env           # điền GEMINI_API_KEY

# 3. Chạy
venv\Scripts\python.exe -m backend.main
# → http://localhost:8000
```

Yêu cầu: Python 3.11+, FFmpeg trong PATH, Node 18+ (nếu build lại frontend).

## Cấu trúc

```
backend/
  main.py                 # entrypoint FastAPI
  api/                    # routers: projects, tasks, voices, library, media, admin
  core/                   # config, database, task_manager, key_pool
  services/               # gemini, tts, video (FFmpeg), ai_studio_bridge
  utils/                  # srt parser, timing
frontend/src/
  app/                    # layout, shell
  features/               # dashboard, projects, tasks, library, ai-studio, settings
  shared/                 # ui primitives, hooks, services
data/                     # runtime: DB, media, cache, logs  (không commit)
```

## Ghi chú thiết kế

- **Không hardcode số phân đoạn.** Model nhận khoảng thời lượng và tự chia cảnh — video 5/7/9 phút
  dùng cùng một prompt, chất lượng ổn định hơn.
- **Timing là bài toán khó nhất.** Lời bình do TTS sinh ra có độ dài thực tế khác dự kiến, nên
  editor phải co giãn clip nguồn (setpts) để tổng thời lượng khớp, thay vì cắt bừa.
- **Giới hạn RAM khi reverse clip.** Clip dài được chia thành các cửa sổ 5s rồi nối, giữ RAM ffmpeg
  dưới ~500MB để không tràn pagefile khi render song song.

## Giấy phép

Mã nguồn dùng cho mục đích học tập và portfolio. Không kèm model/voice của bên thứ ba.
