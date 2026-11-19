"""Router: tải video lên + chế độ thủ công (AI Studio) + tiện ích thư mục."""
import os, time, shutil, threading
from fastapi import APIRouter, File, UploadFile, Form, HTTPException

from backend.core.config import (
    UPLOAD_DIR, MANUAL_DIR, FINAL_DIR, DEFAULT_VOICE, DEFAULT_DETAIL,
    EDIT_MODE_DEFAULT, CHARACTER_NAME_MODE, CHARACTER_REGISTRY,
)
from backend.core.task_manager import task_manager
from backend.services.video_service import get_video_duration
from backend.services.gemini_service import build_scene_prompt
from backend.services.ai_studio_bridge import (
    get_ai_studio_account_info,
    open_login_browser,
    close_automation_browser,
)
from backend.api.deps import (
    logger,
    _compute_targets,
    _setup_manual_task,
    _get_task_series_description,
)
from backend.api.pipeline import process_pipeline, _run_ai_studio_auto

router = APIRouter()


@router.post('/api/upload')
async def upload_file(file: UploadFile = File(...), voice_id: str = Form(DEFAULT_VOICE), style: str = Form('narrative'), model: str = Form(''), mode: str = Form('api'), detail: str = Form(DEFAULT_DETAIL), custom_minutes: str = Form(''), edit_mode: str = Form(EDIT_MODE_DEFAULT), fx_flip: str = Form(''), fx_zoom: str = Form(''), fx_speed: str = Form(''), fx_reverse: str = Form(''), character_name_mode: str = Form(''), free_order: str = Form('')):
    path = os.path.join(UPLOAD_DIR, f'{int(time.time())}_{file.filename}')
    with open(path, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    t = task_manager.create_task(path, {'voice_id': voice_id, 'style': style, 'model': model, 'mode': mode, 'detail': detail, 'custom_minutes': custom_minutes, 'edit_mode': edit_mode, 'fx_flip': fx_flip, 'fx_zoom': fx_zoom, 'fx_speed': fx_speed, 'fx_reverse': fx_reverse, 'character_name_mode': character_name_mode or CHARACTER_NAME_MODE, 'free_order': free_order})
    task_manager.run_task(t, process_pipeline)
    return {'task_id': t.id}


@router.post('/api/manual/start')
async def manual_start(file: UploadFile = File(...), voice_id: str = Form(DEFAULT_VOICE), style: str = Form('narrative'), model: str = Form(''), detail: str = Form(DEFAULT_DETAIL), custom_minutes: str = Form(''), skip_compress: bool = Form(False), edit_mode: str = Form(EDIT_MODE_DEFAULT), fx_flip: str = Form(''), fx_zoom: str = Form(''), fx_speed: str = Form(''), fx_reverse: str = Form(''), character_name_mode: str = Form(''), free_order: str = Form('')):
    path = os.path.join(UPLOAD_DIR, f'{int(time.time())}_{file.filename}')
    with open(path, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    t = task_manager.create_task(path, {'voice_id': voice_id, 'style': style, 'model': model, 'mode': 'manual', 'detail': detail, 'custom_minutes': custom_minutes, 'edit_mode': edit_mode, 'fx_flip': fx_flip, 'fx_zoom': fx_zoom, 'fx_speed': fx_speed, 'fx_reverse': fx_reverse, 'character_name_mode': character_name_mode or CHARACTER_NAME_MODE, 'free_order': free_order})
    t.status = 'awaiting'
    if not skip_compress:
        return _setup_manual_task(t)
    # skip_compress: file nén đã có từ lần prepare trước, chỉ dựng lại prompt.
    target_words, num_segments, target_sec = _compute_targets(t.options)
    prev_dur = 0.0
    try:
        prev_dur = get_video_duration(t.video_path)
    except Exception:
        pass
    t.prompt = build_scene_prompt(style, num_segments, target_words, target_sec, video_duration=prev_dur, characters=t.options.get('characters') or CHARACTER_REGISTRY, name_mode=t.options.get('character_name_mode', CHARACTER_NAME_MODE), series_description=_get_task_series_description(t), free_order=bool(t.options.get('free_order')))
    return {'task_id': t.id, 'prompt': t.prompt, 'compressed_url': None, 'num_segments': num_segments, 'target_words': target_words}


@router.post('/api/manual/auto-run')
async def manual_auto_run(task_id: str = Form(...)):
    """Tự động chạy AI Studio bằng Native GUI: mở/focus Chrome thật -> đính video -> dán prompt -> Run -> trích xuất kết quả."""
    t = task_manager.get_task(task_id)
    if not t:
        raise HTTPException(404, 'Không tìm thấy tác vụ')
    if not t.compressed_path or not os.path.exists(t.compressed_path):
        raise HTTPException(400, 'Chưa có video nén — hãy tạo tác vụ (nút 1) trước')
    if not t.prompt:
        raise HTTPException(400, 'Chưa có lời nhắc — hãy tạo tác vụ trước')

    t.status = 'running'
    t.message = 'Bắt đầu tự động thao tác trên Google AI Studio...'

    threading.Thread(target=lambda: _run_ai_studio_auto(t), daemon=True).start()
    return {'task_id': t.id}


@router.post('/api/manual/open-folder')
async def manual_open_folder(task_id: str = Form(...)):
    t = task_manager.get_task(task_id)
    if not t or not t.compressed_path:
        raise HTTPException(404, 'Chưa có video nén cho tác vụ này')
    folder = os.path.dirname(t.compressed_path)
    # Bảo mật: chỉ cho mở folder trong MANUAL_DIR, không nhận đường dẫn tùy ý từ client
    if not os.path.abspath(folder).startswith(os.path.abspath(MANUAL_DIR)):
        raise HTTPException(400, 'Đường dẫn không hợp lệ')
    if not os.path.isdir(folder):
        raise HTTPException(404, 'Thư mục không tồn tại')
    try:
        os.startfile(folder)
    except Exception as e:
        raise HTTPException(500, f'Không mở được thư mục: {e}')
    return {'ok': True, 'folder': folder}


@router.get('/api/ai-studio/account')
async def ai_studio_get_account():
    """Lấy thông tin tài khoản Google đã đăng nhập cho Chrome Automation (chế độ manual)."""
    try:
        return get_ai_studio_account_info()
    except Exception as e:
        logger.error("Lỗi lấy thông tin tài khoản AI Studio: %s", e)
        raise HTTPException(500, f"Không thể kiểm tra tài khoản: {e}")


@router.post('/api/ai-studio/open-login')
async def ai_studio_open_login():
    """Mở Google Chrome profile automation ở chế độ sạch để người dùng đăng nhập tài khoản Google."""
    try:
        return open_login_browser()
    except Exception as e:
        logger.error("Lỗi mở Chrome đăng nhập: %s", e)
        raise HTTPException(500, f"Không thể mở Chrome: {e}")


@router.post('/api/ai-studio/close-browser')
async def ai_studio_close_browser():
    """Đóng Chrome automation/login để chuẩn bị cho tác vụ tự động hoặc giải phóng profile."""
    try:
        return close_automation_browser()
    except Exception as e:
        logger.error("Lỗi đóng Chrome: %s", e)
        raise HTTPException(500, f"Không thể đóng Chrome: {e}")


@router.post('/api/open-library-folder')
async def open_library_folder():
    """Mở thư mục chứa video tóm tắt đã xuất (output/final)."""
    os.makedirs(FINAL_DIR, exist_ok=True)
    try:
        os.startfile(FINAL_DIR)
    except Exception as e:
        raise HTTPException(500, f'Không mở được thư mục: {e}')
    return {'ok': True, 'folder': FINAL_DIR}


@router.post('/api/manual/submit')
async def manual_submit(task_id: str = Form(...), result_text: str = Form(...)):
    t = task_manager.get_task(task_id)
    if not t:
        raise HTTPException(404, 'Không tìm thấy tác vụ')
    t.result_text = result_text
    task_manager.run_task(t, process_pipeline)
    return {'task_id': t.id}
