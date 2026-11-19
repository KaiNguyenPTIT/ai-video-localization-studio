"""Router: quản lý task (xem/hủy/xóa task đã kết thúc)."""
import os
from fastapi import APIRouter, Query, HTTPException
from backend.core.task_manager import task_manager

router = APIRouter()


@router.get('/api/task/{task_id}')
async def get_task(task_id: str):
    t = task_manager.get_task(task_id)
    if not t: raise HTTPException(404)
    return t.to_dict()


@router.get('/api/tasks')
async def list_tasks(status: str = Query(None)):
    """Liệt kê tất cả tasks. Hỗ trợ filter ?status=running|queueing|completed|failed.

    Danh sách CỐ Ý bỏ `segments` và `prompt` (payload nặng hàng MB) — dùng GET /api/task/{id}
    khi cần xem kịch bản phân cảnh / prompt chi tiết.
    """
    tasks = task_manager.list_tasks()
    if status:
        tasks = [t for t in tasks if t.status == status]
    return {
        'tasks': [
            {**t.to_dict(include_segments=False, include_prompt=False), 'video_name': os.path.basename(t.video_path) if t.video_path else None}
            for t in sorted(tasks, key=lambda t: t.created_at, reverse=True)
        ]
    }


@router.post('/api/tasks/{task_id}/cancel')
async def cancel_task(task_id: str):
    """Hủy task đang xếp hàng chờ."""
    ok = task_manager.cancel_task(task_id)
    if not ok:
        t = task_manager.get_task(task_id)
        if not t:
            raise HTTPException(404, 'Không tìm thấy task')
        raise HTTPException(400, f'Không thể hủy task đang ở trạng thái "{t.status}"')
    return {'ok': True}


@router.delete('/api/tasks/{task_id}')
async def delete_task(task_id: str):
    """Xóa task đã kết thúc khỏi bộ nhớ."""
    ok = task_manager.delete_task(task_id)
    if not ok:
        raise HTTPException(400, 'Chỉ xóa được task đã kết thúc (completed/failed/cancelled)')
    return {'ok': True}


@router.post('/api/tasks/clear-finished')
async def clear_finished_tasks():
    """Xóa tất cả các task đã kết thúc (completed/failed/cancelled) khỏi lịch sử."""
    count = task_manager.clear_finished()
    return {'ok': True, 'count': count}
