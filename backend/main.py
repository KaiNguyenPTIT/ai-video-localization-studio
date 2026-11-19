"""Anime Summarizer — entry point FastAPI.

File này chỉ còn: khởi tạo logging/DB, tạo app, mount static & thư mục output,
middleware heartbeat + vòng giám sát idle, hâm nóng TTS, và gắn các router API
(định nghĩa ở `backend/api/routers/*`). Logic nghiệp vụ nằm ở `backend/api/deps.py`
(helper dùng chung) và `backend/api/pipeline.py` (pipeline xử lý video).
"""
import os, sys, time, threading, logging

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import STATIC_DIR, OUTPUT_DIR, HOST, PORT
from backend.core.logger import init_logging
from backend.core import database

# Khởi tạo ghi log console và file xoay vòng logs/server.log
init_logging()
logger = logging.getLogger('backend.main')

# Khôi phục các tập và tiến trình bị kẹt ở trạng thái queueing/running khi server restart
database.reset_stuck_episodes()
database.recover_interrupted_tasks()
database.seed_tasks_from_episodes()

from backend.api import deps
from backend.api.routers import (
    admin, bridge, library, manual, media, pages, projects, system, tasks, voices,
)

app = FastAPI(title='Anime Summarizer')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
app.mount('/output', StaticFiles(directory=OUTPUT_DIR), name='output')


@app.middleware("http")
async def _activity_tracker_middleware(request, call_next):
    deps.touch_heartbeat()
    return await call_next(request)


def _idle_monitor_loop():
    """Luồng ngầm theo dõi: tắt server sau 5 phút nếu không còn tab nào mở và không có việc bận."""
    time.sleep(120)  # Đợi 2 phút đầu tiên sau khi khởi động
    while True:
        time.sleep(15)
        idle_sec = deps.heartbeat_idle_seconds()

        if idle_sec >= deps.AUTO_SHUTDOWN_TIMEOUT_SEC:
            if deps.is_server_busy():
                deps.touch_heartbeat()
                continue

            logger.info(f"[Auto-Shutdown] Không có tab truy cập sau {int(idle_sec)}s và không có tác vụ bận. Tự động tắt server...")
            os._exit(0)


threading.Thread(target=_idle_monitor_loop, daemon=True, name="IdleMonitor").start()


def _warm_tts_preview_loop():
    """Nạp sẵn file nghe thử TTS dưới nền sau khởi động để click đầu tiên cũng tức thì.

    File lưu tại data/cache/preview/ (sống sót qua /api/cleanup). Giọng nào lỗi
    thì bỏ qua — click vào mới tạo bù."""
    try:
        time.sleep(20)  # nhường khởi động + DB recover xong đã
        from backend.services.tts_service import warm_preview_cache, warm_voicestudio
        n = warm_preview_cache()
        logger.info(f"[TTS] Đã nạp sẵn {n} file nghe thử giọng đọc")
        # Hâm nóng VoiceStudio local (hút cold-start load model khỏi segment đầu tiên).
        try:
            if warm_voicestudio():
                logger.info("[TTS] VoiceStudio đã sẵn sàng (warm-up OK)")
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[TTS] Bỏ qua nạp sẵn giọng nghe thử: {e}")


threading.Thread(target=_warm_tts_preview_loop, daemon=True, name="TTSPreviewWarm").start()


# Gắn toàn bộ router API (URL giữ nguyên như bản monolith cũ)
for _r in (pages, system, manual, projects, voices, library, tasks, bridge, media, admin):
    app.include_router(_r.router)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
