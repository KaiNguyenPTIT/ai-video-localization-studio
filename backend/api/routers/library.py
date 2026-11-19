"""Router: thư viện video thành phẩm + danh mục tài nguyên media."""
import os, json, time
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException

from backend.core.config import FINAL_DIR, OUTPUT_DIR
from backend.core import database
from backend.api.deps import logger

router = APIRouter()


@router.get('/api/media/assets')
async def list_media_assets(episode_id: str = Query(None),
                            project_id: str = Query(None),
                            asset_type: str = Query(None),
                            limit: int = Query(100, ge=1, le=500)):
    """Tra cứu danh mục các tài nguyên đa phương tiện (video gốc, nén, final, srt, tts)."""
    assets = database.get_media_assets(episode_id=episode_id, project_id=project_id,
                                       asset_type=asset_type, limit=limit)
    return {'count': len(assets), 'assets': assets}


@router.post('/api/media/cleanup-orphans')
async def cleanup_media_orphans(delete: bool = Query(False)):
    """Kiểm tra và báo cáo/dọn dẹp các tệp media mồ côi trên ổ cứng không thuộc quản lý của DB."""
    return database.cleanup_orphan_files(delete=delete)


@router.get('/api/library')
async def get_library():
    """Trả về danh sách các sản phẩm hoàn chỉnh đã xuất (gộp video .mp4 và sub .srt vào cùng 1 mục)."""
    groups = {}
    if os.path.isdir(FINAL_DIR):
        for fname in sorted(os.listdir(FINAL_DIR), reverse=True):
            fp = os.path.join(FINAL_DIR, fname)
            if not os.path.isfile(fp):
                continue
            base, ext = os.path.splitext(fname)
            ext = ext.lower()
            if ext not in ('.mp4', '.srt', '.mkv', '.webm'):
                continue

            mtime = os.path.getmtime(fp)
            if base not in groups:
                clean_title = base
                if '_summary_' in clean_title:
                    clean_title = clean_title.split('_summary_')[0]
                if '_' in clean_title and clean_title.split('_')[0].isdigit():
                    clean_title = clean_title.split('_', 1)[1]

                groups[base] = {
                    'base_name': base,
                    'title': clean_title or base,
                    'modified_at': datetime.fromtimestamp(mtime).isoformat(),
                    'video': None,
                    'srt': None,
                }

            rel = os.path.relpath(fp, OUTPUT_DIR).replace('\\', '/')
            if ext in ('.mp4', '.mkv', '.webm'):
                groups[base]['video'] = {
                    'filename': fname,
                    'size_mb': round(os.path.getsize(fp) / 1024 / 1024, 2),
                    'url': f'/media/{rel}',
                    'media_url': f'/media/{rel}'
                }
            elif ext == '.srt':
                groups[base]['srt'] = {
                    'filename': fname,
                    'size_kb': round(os.path.getsize(fp) / 1024, 1),
                    'url': f'/output/{rel}'
                }

        # Gắn metadata merge (nếu có) để thư viện hiển thị danh sách tập + timestamp
        for gbase in groups:
            meta_path = os.path.join(FINAL_DIR, gbase + '.merge.json')
            if os.path.isfile(meta_path) and groups[gbase]['video']:
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    groups[gbase]['merge'] = {
                        'project_id': meta.get('project_id'),
                        'project_name': meta.get('project_name'),
                        'srt_url': meta.get('srt_url'),
                        'episode_ranges': meta.get('episode_ranges') or [],
                        'total_duration': meta.get('total_duration'),
                    }
                except Exception:
                    pass

    items = list(groups.values())
    items.sort(key=lambda x: x['modified_at'], reverse=True)
    return {'items': items, 'total': len(items)}


def _robust_remove_file(fp: str, retries: int = 6, delay: float = 0.5) -> tuple[bool, str | None]:
    """Xóa file, thử lại khi bị khóa tạm (Windows WinError 32 do trình phát/preview

    đang giữ handle). Trả về (True, None) nếu xóa xong, (False, lý_do) nếu vẫn kẹt.
    Chỉ dùng cho file trong OUTPUT_DIR (thư viện) — không đụng uploads/."""
    import gc
    last_err = None
    for attempt in range(retries):
        try:
            os.remove(fp)
            return True, None
        except FileNotFoundError:
            return True, None
        except OSError as e:
            last_err = str(e)
            # Lần cuối thì thôi, các lần trước dọn handle thừa + chờ process nhả lock.
            if attempt < retries - 1:
                try:
                    gc.collect()
                except Exception:
                    pass
                time.sleep(delay)
    logger.warning(f"[DEL] Không xóa được {fp} sau {retries} lần thử (file đang mở/khóa?): {last_err}")
    return False, last_err


@router.delete('/api/library/{base_name:path}')
async def delete_library_item(base_name: str):
    """Xóa trọn bộ cả file video và srt của một mục khỏi thư mục final và đồng bộ ngược về Dự án phim.

    CHỈ đụng file trong output/final — video gốc trong uploads/ được giữ nguyên."""
    if '/' in base_name or '\\' in base_name or '..' in base_name:
        raise HTTPException(400, 'Tên không hợp lệ')

    # 1. Đọc project_id nếu là file merge trước khi xóa
    meta_path = os.path.join(FINAL_DIR, base_name + '.merge.json')
    meta_project_id = None
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                meta_project_id = meta.get('project_id')
        except Exception:
            pass

    # 2. Xóa các tệp vật lý trên đĩa (CHỈ trong output/final)
    video_exts = ('.mp4', '.mkv', '.webm')
    deleted = []
    failed = []
    for ext in ('.mp4', '.srt', '.mkv', '.webm', '.merge.json'):
        fname = base_name + ext
        fp = os.path.join(FINAL_DIR, fname)
        if os.path.isfile(fp):
            ok, err = _robust_remove_file(fp)
            if ok:
                deleted.append(fname)
            else:
                failed.append({'file': fname, 'error': err or 'File đang được mở/khóa bởi tiến trình khác'})

    # Không còn file nào trên đĩa mà cũng chẳng xóa được gì (toàn bộ bị khóa) →
    # báo 409 để UI nhắc user đóng trình phát rồi thử lại, KHÔNG reset DB sai lệch.
    if failed and not deleted:
        raise HTTPException(
            409,
            f"Không xóa được {len(failed)} file (đang mở/khóa?). Hãy đóng trình phát video rồi thử lại: "
            + ', '.join(f['file'] for f in failed),
        )

    # 3. Đồng bộ ngược về cơ sở dữ liệu — CHỈ khi file video đã biến mất thật
    # (xóa xong hoặc vốn đã không còn). Nếu video vẫn còn trên đĩa (xóa lỗi/khóa)
    # thì giữ nguyên link episode, tránh reset về pending trong khi file vẫn xem được.
    video_gone = not any(
        os.path.isfile(os.path.join(FINAL_DIR, base_name + e)) for e in video_exts
    )
    if video_gone:
        sync_res = database.sync_on_library_deleted(base_name, project_id=meta_project_id)
    else:
        sync_res = {'affected_episodes': 0, 'skipped': 'video vẫn còn trên đĩa, giữ nguyên liên kết tập phim'}

    return {'ok': len(failed) == 0, 'deleted': deleted, 'failed': failed, 'synced': sync_res}
