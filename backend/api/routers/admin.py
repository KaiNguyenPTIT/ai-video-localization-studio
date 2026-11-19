"""Router: bảng điều khiển Admin (đăng nhập, cài đặt, thông tin hệ thống, log, model Gemini)."""
import os, time, threading, secrets
from fastapi import APIRouter, Form, Query, Cookie, HTTPException
from fastapi.responses import JSONResponse

from backend.core.config import (
    ADMIN_SCHEMA, ADMIN_PASSWORD, ADMIN_SETTINGS_FILE,
    load_admin_settings, save_admin_settings, get_current_settings,
    GEMINI_MODEL, BASE_DIR, SEGMENTS_DIR, AUDIO_DIR, TEMP_DIR, UPLOAD_DIR, LOGS_DIR,
    get_models, add_model as _add_model, update_model as _update_model, remove_model as _remove_model,
)
from backend.core.task_manager import task_manager
from backend.core import key_pool
from backend.core import database

router = APIRouter()

_admin_sessions = {}  # token -> expiry_timestamp
_admin_lock = threading.Lock()


def _check_admin(token: str = None) -> bool:
    if not token:
        return False
    with _admin_lock:
        exp = _admin_sessions.get(token)
        if exp and time.time() < exp:
            return True
        _admin_sessions.pop(token, None)
    return False


# (Trang /admin cũ đã bỏ — dùng tab "Tinh chỉnh đầu ra" + "Công cụ Admin" trong React.
#  Các endpoint /api/admin/* vẫn giữ nguyên cho client mới.)
@router.post('/api/admin/login')
async def admin_login(password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(401, 'Sai mật khẩu')
    token = secrets.token_hex(32)
    with _admin_lock:
        _admin_sessions[token] = time.time() + 86400  # 24h
    return JSONResponse({'ok': True, 'token': token}, headers={
        'Set-Cookie': f'admin_token={token}; Path=/api/admin; HttpOnly; SameSite=Lax; Max-Age=86400'
    })


@router.get('/api/admin/settings')
async def admin_get_settings(admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    current = get_current_settings()
    return {'settings': current, 'schema': ADMIN_SCHEMA}


@router.post('/api/admin/settings')
async def admin_save_settings(updates: dict = None, admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    if not updates:
        raise HTTPException(400, 'Không có dữ liệu')
    saved = save_admin_settings(updates)
    return {'ok': True, 'settings': saved}


@router.get('/api/admin/system')
async def admin_system_info(admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    import platform
    import subprocess as _sp

    py_ver = platform.python_version()
    ff_ver = '?'
    try:
        r = _sp.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        first = (r.stdout or '').split('\n')[0]
        ff_ver = first.split(' ')[2] if len(first.split(' ')) > 2 else first
    except Exception:
        pass

    gpu_info = '?'
    try:
        r = _sp.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader,nounits'],
                     capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split(', ')
            gpu_info = f"{parts[0]} (Driver {parts[1]}, {parts[2]} MB)" if len(parts) >= 3 else r.stdout.strip()
    except Exception:
        pass

    ram_total = ram_avail = 0
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        ram_total = round(m.ullTotalPhys / (1024**3), 1)
        ram_avail = round(m.ullAvailPhys / (1024**3), 1)
    except Exception:
        pass

    disk_total = disk_free = 0
    try:
        import shutil as _sh
        usage = _sh.disk_usage(BASE_DIR)
        disk_total = round(usage.total / (1024**3), 1)
        disk_free = round(usage.free / (1024**3), 1)
    except Exception:
        pass

    keys = key_pool.get_keys()
    return {
        'python': py_ver, 'ffmpeg': ff_ver, 'gpu': gpu_info,
        'platform': f'{platform.system()} {platform.release()}',
        'ram_total_gb': ram_total, 'ram_avail_gb': ram_avail,
        'disk_total_gb': disk_total, 'disk_free_gb': disk_free,
        'api_keys': len(keys), 'workers': task_manager._num_workers,
        'queue_depth': task_manager.worker_queue.qsize(),
    }


@router.get('/api/admin/logs')
async def admin_logs(lines: int = Query(100), admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    log_content = ''
    for log_path in [os.path.join(LOGS_DIR, 'server.log'), 'server.log',
                     os.path.join(BASE_DIR, 'server.log')]:
        if os.path.isfile(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    all_lines = f.readlines()
                log_content = ''.join(all_lines[-lines:])
                break
            except Exception:
                pass
    return {'log': log_content, 'lines': lines}


@router.post('/api/admin/restart')
async def admin_restart(admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    def _do_restart():
        import sys, subprocess
        time.sleep(0.8)
        if os.getenv('MANAGED_BY_RUN_BAT') != '1':
            relaunch_code = (
                "import time, subprocess, sys\n"
                "time.sleep(2)\n"
                f"subprocess.Popen([{repr(sys.executable)}, '-m', 'backend.main'], cwd={repr(BASE_DIR)})\n"
            )
            creationflags = 0x08000000 if os.name == 'nt' else 0
            subprocess.Popen(
                [sys.executable, "-c", relaunch_code],
                cwd=BASE_DIR,
                creationflags=creationflags,
                close_fds=True
            )
        os._exit(0)
    threading.Thread(target=_do_restart, daemon=True).start()
    return {'ok': True, 'message': 'Server sẽ khởi động lại...'}


@router.post('/api/admin/cleanup')
async def admin_cleanup(admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    database.reset_stuck_episodes()
    freed = 0
    count = 0
    for d in [SEGMENTS_DIR, AUDIO_DIR, TEMP_DIR]:
        if os.path.isdir(d):
            for fn in os.listdir(d):
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    try:
                        freed += os.path.getsize(fp)
                        os.remove(fp)
                        count += 1
                    except Exception:
                        pass
    now = time.time()
    if os.path.isdir(UPLOAD_DIR):
        for fn in os.listdir(UPLOAD_DIR):
            fp = os.path.join(UPLOAD_DIR, fn)
            if os.path.isfile(fp) and (now - os.path.getmtime(fp) > 86400):
                try:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
                    count += 1
                except Exception:
                    pass
    return {'ok': True, 'freed_mb': round(freed / (1024 * 1024), 2), 'deleted': count}


# ── Gemini Model Management ──

@router.get('/api/admin/models')
async def admin_get_models(admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    return {'models': get_models(), 'current': GEMINI_MODEL}


@router.post('/api/admin/models')
async def admin_add_model(payload: dict = None, admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    if not payload or not payload.get('id'):
        raise HTTPException(400, 'Thiếu model id')
    try:
        models = _add_model(payload['id'], payload.get('name', ''))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True, 'models': models}


@router.put('/api/admin/models/{index}')
async def admin_update_model(index: int, payload: dict = None, admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    try:
        models = _update_model(index, payload.get('id') if payload else None, payload.get('name') if payload else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True, 'models': models}


@router.delete('/api/admin/models/{index}')
async def admin_remove_model(index: int, admin_token: str = Cookie(None)):
    if not _check_admin(admin_token):
        raise HTTPException(401, 'Chưa đăng nhập')
    try:
        models = _remove_model(index)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True, 'models': models, 'current': GEMINI_MODEL}
