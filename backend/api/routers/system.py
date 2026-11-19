"""Router: hệ thống & tiện ích — heartbeat, danh sách giọng/model, health, storage,
API key pool, preview giọng, thống kê, nhật ký, dọn dẹp cache."""
import os
import asyncio
from fastapi import APIRouter, Form, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.core.config import (
    VOICES, DEFAULT_VOICE, GEMINI_MODELS, GEMINI_MODEL, DETAIL_LEVELS, DEFAULT_DETAIL,
    UPLOAD_DIR, TEMP_DIR, AUDIO_DIR, SEGMENTS_DIR, FINAL_DIR, MANUAL_DIR,
)
from backend.core.task_manager import task_manager
from backend.core import key_pool
from backend.core import database
from backend.core.logger import read_logs, clear_logs
from backend.services.tts_service import preview_voice as _preview_voice

from backend.api.deps import (
    logger, _cache_get, _cache_set, touch_heartbeat,
)

router = APIRouter()


@router.post('/api/heartbeat')
async def client_heartbeat():
    touch_heartbeat()
    return {'ok': True}


@router.get('/api/voices')
async def get_voices():
    # `_load_voicestudio_voices` có thể gọi mạng tới VoiceStudio local (blocking) — chạy ở
    # threadpool để không chặn event loop, và cache ~10s để tránh dò lại liên tục.
    cached = _cache_get('voices', 30.0)
    if cached is None:
        def _load():
            from backend.core.config import _load_voicestudio_voices
            try:
                VOICES.update(_load_voicestudio_voices())
            except Exception:
                pass
            return dict(VOICES)
        cached = await run_in_threadpool(_load)
        _cache_set('voices', cached)
    return {'voices': cached}


@router.get('/api/voicestudio/status')
async def get_voicestudio_status():
    from backend.services.voicestudio_service import check_health, VOICESTUDIO_API_BASE
    # `check_health` là lời gọi mạng đồng bộ (có thể block tới vài giây khi server local treo).
    # Chạy ở threadpool + cache ngắn để các poll từ UI không làm nghẽn event loop.
    cached = _cache_get('vs_status', 15.0)
    if cached is None:
        cached = await run_in_threadpool(lambda: check_health(timeout=1.0))
        _cache_set('vs_status', cached)
    ok, msg = cached
    return {'online': ok, 'message': msg, 'api_base': VOICESTUDIO_API_BASE}


@router.get('/api/models')
async def get_models():
    return {'models': GEMINI_MODELS}


@router.get('/api/detail-levels')
async def get_detail_levels():
    return {'levels': DETAIL_LEVELS, 'default': DEFAULT_DETAIL}


@router.get('/api/health')
async def get_health():
    keys = key_pool.get_keys()
    queue_depth = task_manager.worker_queue.qsize()
    active = sum(
        1 for t in task_manager.list_tasks()
        if t.status in ('pending', 'queueing', 'running', 'awaiting')
    )
    return {
        'status': 'ok',
        'gemini_keys': len(keys),
        'workers': task_manager._num_workers,
        'queue_depth': queue_depth,
        'active_tasks': active,
        'model': GEMINI_MODEL,
    }


def _dir_size_mb(path):
    total = 0
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except Exception:
                    pass
    return round(total / (1024 * 1024), 2)


@router.get('/api/storage')
async def get_storage():
    protected_basenames = set()
    protected_paths = set()
    try:
        projects = database.get_all_projects()
        for p in projects:
            for ep in p.get('episodes', []):
                vp = ep.get('video_path')
                if vp:
                    protected_paths.add(os.path.normcase(os.path.abspath(vp)))
                    protected_basenames.add(os.path.basename(vp).lower())
    except Exception:
        pass

    project_uploads_mb = 0.0
    orphan_uploads_mb = 0.0
    if os.path.isdir(UPLOAD_DIR):
        for fname in os.listdir(UPLOAD_DIR):
            fp = os.path.join(UPLOAD_DIR, fname)
            if os.path.isfile(fp):
                sz_mb = round(os.path.getsize(fp) / (1024 * 1024), 2)
                norm_fp = os.path.normcase(os.path.abspath(fp))
                if norm_fp in protected_paths or fname.lower() in protected_basenames:
                    project_uploads_mb += sz_mb
                else:
                    orphan_uploads_mb += sz_mb

    temp_mb = _dir_size_mb(TEMP_DIR)
    audio_mb = _dir_size_mb(AUDIO_DIR)
    segments_mb = _dir_size_mb(SEGMENTS_DIR)
    cleanable_mb = round(temp_mb + audio_mb + segments_mb + orphan_uploads_mb, 2)

    return {
        'output': _dir_size_mb(FINAL_DIR),
        'temporary': temp_mb,
        'audio': audio_mb,
        'segments': segments_mb,
        'uploads': round(project_uploads_mb + orphan_uploads_mb, 2),
        'project_uploads': round(project_uploads_mb, 2),
        'orphan_uploads': round(orphan_uploads_mb, 2),
        'cleanable': cleanable_mb,
        'manual': _dir_size_mb(MANUAL_DIR),
        'total': round(sum([
            _dir_size_mb(FINAL_DIR), temp_mb,
            audio_mb, segments_mb,
            project_uploads_mb + orphan_uploads_mb, _dir_size_mb(MANUAL_DIR),
        ]), 2),
    }


@router.get('/api/keys')
async def get_keys():
    keys = key_pool.get_keys()
    return {'keys': keys, 'count': len(keys),
            'masked': [k[:6] + '...' + k[-4:] if len(k) > 12 else '***' for k in keys]}


@router.post('/api/keys')
async def set_keys(keys: str = Form('')):
    """Nhận danh sách key cách nhau dấu phẩy, lưu vào .env."""
    saved = key_pool.set_keys([k.strip() for k in keys.split(',') if k.strip()])
    # Tự động scale worker song song theo số key mới
    task_manager.scale_workers()
    return {'saved': saved, 'count': len(saved),
            'workers': task_manager._num_workers,
            'masked': [k[:6] + '...' + k[-4:] if len(k) > 12 else '***' for k in saved]}


@router.post('/api/keys/test')
async def test_key(payload: dict = None):
    """Kiểm tra 1 key có sống không bằng cách list models (request nhẹ, không tốn
    quota generate). Nhận {"index": i} — server tự lấy key từ pool, không cần gửi
    key qua mạng. Chạy trên threadpool + timeout để không block event loop."""
    import asyncio as _asyncio
    keys = key_pool.get_keys()
    if payload is None or 'index' not in payload:
        raise HTTPException(400, 'Thiếu index')
    try:
        idx = int(payload['index'])
    except Exception:
        raise HTTPException(400, 'index không hợp lệ')
    if not (0 <= idx < len(keys)):
        raise HTTPException(400, 'index vượt quá danh sách key')
    key = keys[idx]
    masked = key[:6] + '...' + key[-4:] if len(key) > 12 else '***'

    def _do_test():
        from backend.services.gemini_service import _client_for, _close_client
        client = None
        try:
            client = _client_for(key)
            pager = client.models.list(config={'page_size': 3})
            items = list(pager)
            return {'ok': True, 'key_index': idx, 'masked': masked, 'model_count': len(items)}
        except Exception as e:
            msg = str(e)[:150]
            return {'ok': False, 'key_index': idx, 'masked': masked, 'error': msg or type(e).__name__}
        finally:
            try:
                _close_client(client)
            except Exception:
                pass

    try:
        return await _asyncio.wait_for(_asyncio.to_thread(_do_test), timeout=30)
    except _asyncio.TimeoutError:
        raise HTTPException(504, f'Key {masked} timeout (mạng kẹt?)')


@router.get('/api/preview')
async def preview(voice: str = Query(DEFAULT_VOICE), text: str = Query('')):
    if voice not in VOICES:
        return JSONResponse(status_code=400, content={'detail': 'Giọng không hợp lệ'})
    try:
        # synthesize chặn (gọi API CapCut / model local) → chạy threadpool để không treo event loop;
        # đã có cache đĩa nên lần 2+ xong trong vài ms.
        path = await asyncio.to_thread(_preview_voice, voice, (text or '')[:200])
    except Exception as e:
        err_msg = str(e)
        logger.warning(f'[Preview] Lỗi tạo preview cho giọng {voice}: {err_msg}')
        status = 503 if ('VoiceStudio' in err_msg or 'kết nối' in err_msg.lower()) else 500
        return JSONResponse(status_code=status, content={'detail': err_msg})
    return FileResponse(path, media_type='audio/mpeg', filename=os.path.basename(path))


@router.get('/api/stats')
async def get_stats():
    """Thống kê tổng quát cho Studio Dashboard."""
    import platform
    task_stats = task_manager.get_stats()
    projects   = database.get_all_projects()

    total_episodes = sum(len(p.get('episodes', [])) for p in projects)
    done_episodes  = sum(
        sum(1 for e in p.get('episodes', []) if e['status'] == 'completed')
        for p in projects
    )

    # Dung lượng output/final
    total_size_mb = 0
    file_count    = 0
    if os.path.isdir(FINAL_DIR):
        for f in os.listdir(FINAL_DIR):
            fp = os.path.join(FINAL_DIR, f)
            if os.path.isfile(fp):
                total_size_mb += os.path.getsize(fp)
                file_count    += 1
    total_size_mb /= 1024 * 1024

    return {
        'projects':     len(projects),
        'episodes':     {'total': total_episodes, 'completed': done_episodes},
        'tasks':        task_stats,
        'output_files': file_count,
        'output_size_mb': round(total_size_mb, 1),
        'queue_depth':  task_manager.worker_queue.qsize(),
    }


@router.get('/api/logs')
async def get_system_logs(
    lines: int = Query(300, ge=10, le=2000),
    level: str = Query(None),
    search: str = Query(None)
):
    """Lấy nhật ký hệ thống gần nhất từ file logs/server.log."""
    return read_logs(limit=lines, level=level, search=search)


@router.delete('/api/logs')
async def delete_system_logs():
    """Làm sạch file nhật ký hệ thống."""
    ok = clear_logs()
    return {'ok': ok}


@router.post('/api/cleanup')
async def cleanup_cache():
    """Dọn dẹp các file rác trung gian (segments, audio, temp, uploads cũ mồ côi).
    Bảo vệ an toàn 100%:
    1. Tuyệt đối không xóa bất kỳ video gốc nào của các tập phim trong cơ sở dữ liệu.
    2. Không xóa các file vừa tạo trong vòng 1 giờ nếu đang có tác vụ chạy ngầm.
    3. Tự động đồng bộ các bản ghi media_assets mồ côi trong cơ sở dữ liệu SQLite.
    """
    import time as _time
    freed_bytes = 0
    deleted_count = 0
    now = _time.time()

    # 1. Thu thập tất cả tên file và đường dẫn video của các tập phim trong DB để BẢO VỆ TUYỆT ĐỐI
    protected_basenames = set()
    protected_paths = set()
    try:
        projects = database.get_all_projects()
        for p in projects:
            for ep in p.get('episodes', []):
                vp = ep.get('video_path')
                if vp:
                    protected_paths.add(os.path.normcase(os.path.abspath(vp)))
                    protected_basenames.add(os.path.basename(vp).lower())
    except Exception as e:
        logger.warning(f"Lỗi truy vấn project episodes khi dọn dẹp: {e}")

    # 2. Kiểm tra xem có tác vụ nào đang chạy hay xếp hàng không
    has_running_tasks = any(
        t.status in ('running', 'queueing')
        for t in task_manager.tasks.values()
    )

    cleanup_dirs = [SEGMENTS_DIR, AUDIO_DIR, TEMP_DIR]

    for cdir in cleanup_dirs:
        if os.path.isdir(cdir):
            for fname in os.listdir(cdir):
                fp = os.path.join(cdir, fname)
                if os.path.isfile(fp):
                    # Nếu có tác vụ đang chạy, bảo vệ các file tạo/sửa trong vòng 1 giờ qua
                    if has_running_tasks and (now - os.path.getmtime(fp) < 3600):
                        continue
                    try:
                        sz = os.path.getsize(fp)
                        os.remove(fp)
                        freed_bytes += sz
                        deleted_count += 1
                    except Exception:
                        pass

    # 3. Dọn uploads cũ hơn 24 giờ NHƯNG TUYỆT ĐỐI BẢO VỆ FILE GỐC CỦA TẬP PHIM
    if os.path.isdir(UPLOAD_DIR):
        for fname in os.listdir(UPLOAD_DIR):
            fp = os.path.join(UPLOAD_DIR, fname)
            norm_fp = os.path.normcase(os.path.abspath(fp))
            # Nếu file khớp với bất kỳ episode nào trong DB (cả path lẫn basename) -> BẢO VỆ
            if norm_fp in protected_paths or fname.lower() in protected_basenames:
                continue
            # Chỉ xóa file mồ côi (tải lên nhanh nhưng không dùng, cũ hơn 24 giờ)
            if os.path.isfile(fp) and (now - os.path.getmtime(fp) > 86400):
                try:
                    sz = os.path.getsize(fp)
                    os.remove(fp)
                    freed_bytes += sz
                    deleted_count += 1
                except Exception:
                    pass

    # 4. Đồng bộ dọn dẹp các bản ghi tạm thời không còn file trên đĩa trong SQLite
    try:
        with database.get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id, file_path FROM media_assets WHERE is_temporary = 1;")
            orphan_ids = [r['id'] for r in cur.fetchall() if not (r['file_path'] and os.path.isfile(r['file_path']))]
            if orphan_ids:
                cur.execute(f"DELETE FROM media_assets WHERE id IN ({','.join(['?']*len(orphan_ids))});", orphan_ids)
    except Exception as e:
        logger.warning(f"Lỗi dọn dẹp media_assets mồ côi: {e}")

    return {
        'ok': True,
        'freed_mb': round(freed_bytes / (1024 * 1024), 2),
        'deleted_count': deleted_count
    }
