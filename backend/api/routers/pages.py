"""Router: trang HTML tĩnh (SPA shell)."""
import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from backend.core.config import STATIC_DIR

router = APIRouter()


@router.get('/', response_class=HTMLResponse)
@router.get('/quick', response_class=HTMLResponse)
@router.get('/studio', response_class=HTMLResponse)
@router.get('/studio/{project_id}', response_class=HTMLResponse)
@router.get('/projects', response_class=HTMLResponse)
@router.get('/projects/{project_id}', response_class=HTMLResponse)
@router.get('/tasks', response_class=HTMLResponse)
@router.get('/library', response_class=HTMLResponse)
@router.get('/settings', response_class=HTMLResponse)
@router.get('/storage', response_class=HTMLResponse)
@router.get('/logs', response_class=HTMLResponse)
async def index(project_id: str = None):
    with open(os.path.join(STATIC_DIR, 'index.html'), encoding='utf-8') as f:
        return f.read()
