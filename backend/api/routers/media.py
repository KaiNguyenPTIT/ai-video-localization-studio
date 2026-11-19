"""Router: phục vụ file media với HTTP Range (video/audio trong OUTPUT_DIR)."""
import os
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from backend.core.config import OUTPUT_DIR

router = APIRouter()

# Chunk đọc file cho endpoint /media (stream từng phần, tránh buffer khổng lồ)
_MEDIA_CHUNK = 1024 * 1024  # 1MB


@router.get('/media/{path:path}')
async def media(path: str, range_header: str = Header(None, alias='Range')):
    """Phục vụ file (video/audio) hỗ trợ HTTP Range để trình phát web tua được.

    Starlette FileResponse/StaticFiles trong bản đang dùng không xử lý Range header
    (luôn trả 200 cả file) -> browser không seek được -> tự implement range ở đây.
    """
    full = os.path.abspath(os.path.join(OUTPUT_DIR, path))
    root = os.path.abspath(OUTPUT_DIR)
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, 'File không tồn tại')
    size = os.path.getsize(full)
    ctype = 'video/mp4'
    if full.lower().endswith(('.mp3', '.wav')):
        ctype = 'audio/mpeg' if full.lower().endswith('.mp3') else 'audio/wav'

    def _send(start: int, end: int, status: int, content_range):
        # Stream từng chunk 1MB thay vì đọc cả file vào 1 buffer: file video gộp
        # nhiều GB trong một Response(content=...) sẽ làm sập WSASend của asyncio
        # trên Windows (ValueError: buffer too large) + block event loop khi đọc.
        # Sync generator được Starlette chạy trên threadpool nên không block loop;
        # client ngắt giữa chừng (Chrome probe bytes=0- rồi hủy) thì generator dừng.
        def _iter():
            with open(full, 'rb') as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    data = f.read(min(_MEDIA_CHUNK, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
        headers = {'Content-Type': ctype, 'Accept-Ranges': 'bytes',
                   'Content-Length': str(end - start + 1)}
        if content_range:
            headers['Content-Range'] = content_range
        return StreamingResponse(_iter(), status_code=status, headers=headers, media_type=ctype)

    rng = None
    if range_header and range_header.startswith('bytes='):
        rng = range_header[6:].split(',')[0].strip()
    if not rng:
        return _send(0, size - 1, 200, None)
    try:
        if rng.endswith('-'):
            start = int(rng[:-1])
            end = size - 1
        elif rng.startswith('-'):
            suffix = int(rng[1:])
            start = max(0, size - suffix)
            end = size - 1
        else:
            a, b = rng.split('-')
            start, end = int(a), int(b if b else size - 1)
        if start > end or start >= size:
            return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
        end = min(end, size - 1)
    except Exception:
        return _send(0, size - 1, 200, None)
    return _send(start, end, 206, f'bytes {start}-{end}/{size}')
