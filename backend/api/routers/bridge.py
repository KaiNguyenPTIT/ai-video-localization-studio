"""Router: bridge cho userscript AI Studio (lấy task chờ, cập nhật trạng thái, trả kịch bản)."""
import os
from fastapi import APIRouter, Form, HTTPException
from backend.core.config import OUTPUT_DIR
from backend.core.task_manager import task_manager
from backend.api.pipeline import process_pipeline

router = APIRouter()


@router.get('/api/bridge/pending-task')
async def bridge_pending_task():
    """Userscript trong AI Studio gọi định kỳ để lấy task đang chờ."""
    for tid, t in list(task_manager.tasks.items()):
        if t.status == 'awaiting' and t.prompt and t.compressed_path:
            return {
                'task': {
                    'id': t.id,
                    'prompt': t.prompt,
                    'video_url': f'/output/{os.path.relpath(t.compressed_path, OUTPUT_DIR).replace(chr(92), "/")}',
                    'video_name': os.path.basename(t.compressed_path),
                    'model': t.options.get('model', ''),
                }
            }
    return {'task': None}


@router.post('/api/bridge/update-status')
async def bridge_update_status(task_id: str = Form(...), message: str = Form(...), progress: int = Form(None)):
    """Userscript cập nhật tiến trình."""
    t = task_manager.get_task(task_id)
    if not t:
        raise HTTPException(404, 'Không tìm thấy tác vụ')
    t.message = message
    if progress is not None:
        t.progress = progress
    return {'ok': True}


@router.post('/api/bridge/complete-task')
async def bridge_complete_task(task_id: str = Form(...), result_text: str = Form(...)):
    """Userscript gửi kịch bản hoàn chỉnh về -> tiếp tục chạy pipeline tạo video."""
    t = task_manager.get_task(task_id)
    if not t:
        raise HTTPException(404, 'Không tìm thấy tác vụ')
    t.result_text = result_text
    t.status = 'running'
    t.message = 'Đã nhận kịch bản từ Userscript AI Studio. Đang tiến hành tạo video...'
    task_manager.run_task(t, process_pipeline)
    return {'ok': True, 'task_id': t.id}
