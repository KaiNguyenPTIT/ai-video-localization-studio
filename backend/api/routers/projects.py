"""Router: dự án phim, tập phim, kịch bản, nhân vật, tùy chọn & quy trình xử lý."""
import os, re, json, shutil, threading, hashlib, time
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, Form, Query, Body, HTTPException

from backend.core.config import (
    OUTPUT_DIR, FINAL_DIR, UPLOAD_DIR, TEMP_DIR, MANUAL_DIR, VOICE_REF_DIR,
    DEFAULT_VOICE, GEMINI_MODEL, DEFAULT_DETAIL, CHARACTER_NAME_MODE,
)
from backend.core.task_manager import task_manager
from backend.core import database
from backend.services.gemini_service import (
    extract_characters_from_script, normalize_character_names,
    _collapse_doubled_prefix, CHARACTER_STOPWORDS,
)
from backend.services.video_service import concat_videos, get_video_duration, create_srt
from backend.utils.srt_parser import time_to_seconds, seconds_to_time_short

from backend.api.deps import (
    logger,
    _effective_options,
    _episode_updater,
    _delete_episode_outputs,
    _delete_episode_related_files,
    _setup_manual_task,
    _prepare_manual_prompt,
)
from backend.api.pipeline import process_pipeline, _run_ai_studio_auto

router = APIRouter()


@router.get('/api/projects')
async def get_projects():
    return {'projects': database.get_all_projects()}


@router.post('/api/projects')
async def create_project(name: str = Form(...), settings: str = Form(None)):
    import json as _json
    parsed_settings = None
    if settings:
        try:
            parsed_settings = _json.loads(settings)
        except Exception:
            pass
    if not parsed_settings:
        parsed_settings = {
            'voice_id': DEFAULT_VOICE,
            'model': GEMINI_MODEL,
            'style': 'narrative',
            'detail': DEFAULT_DETAIL
        }
    p = database.create_project(name, settings=parsed_settings)
    return p


@router.get('/api/projects/{project_id}')
async def get_project(project_id: str):
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    return p


@router.post('/api/projects/{project_id}/merge')
async def merge_project(project_id: str, payload: dict = None):
    """Ghép video đầu ra của các tập trong project thành 1 video liên tục (theo thứ tự episodes).

    Body (tùy chọn): {"episode_ids": ["id1", "id2", ...]} → chỉ ghép các tập được chọn.
    Nếu không có body → ghép toàn bộ tập status='completed' có result_url.
    Bỏ qua tập chưa hoàn thành / không có file đầu ra."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')

    episodes = p.get('episodes', [])
    if payload and payload.get('episode_ids'):
        wanted = set(payload['episode_ids'])
        ordered = [ep for ep in episodes if ep.get('id') in wanted and ep.get('status') == 'completed']
    else:
        ordered = [ep for ep in episodes if ep.get('status') == 'completed']

    if not ordered:
        raise HTTPException(400, 'Không có tập hoàn thành nào để ghép.')

    pairs = []
    for ep in ordered:
        url = ep.get('result_url') or ''
        if not url:
            continue
        # result_url dạng /media/{rel_to_output}
        rel = url.split('/media/', 1)[-1].replace('/', os.sep)
        full = os.path.abspath(os.path.join(OUTPUT_DIR, rel))
        if full.startswith(os.path.abspath(OUTPUT_DIR) + os.sep) and os.path.isfile(full):
            pairs.append((ep, full))

    paths = [v for _, v in pairs]
    if len(paths) < 2:
        raise HTTPException(400, f'Cần ít nhất 2 tập hoàn thành có video để ghép (hiện {len(paths)}).')

    os.makedirs(FINAL_DIR, exist_ok=True)
    name_slug = re.sub(r'[^\w\-]+', '_', p.get('name', 'project')).strip('_')[:40]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_out = f'{name_slug}_merged_{ts}'
    out = os.path.join(FINAL_DIR, base_out + '.mp4')

    def _run_merge(task):
        """Chạy merge + gộp SRT + metadata trên worker thread nền để KHÔNG block event loop
        (tránh đứng giao diện trong lúc ffmpeg re-encode)."""
        task.progress = 5
        task.message = 'Đang ghép video (nối các tập)...'
        if task.on_update: task.on_update()

        merge_work_dir = os.path.join(TEMP_DIR, 'merge_' + project_id)
        os.makedirs(merge_work_dir, exist_ok=True)
        # Video các tập đồng nhất codec/tham số (cùng pipeline) → thử nối copy trước
        # (nhanh ~20×, giữ nguyên chất lượng); lệch/thất bại tự rơi về re-encode.
        concat_videos(paths, out, work_dir=merge_work_dir, try_copy_first=True)
        task.progress = 70
        task.message = 'Đang tổng hợp phụ đề...'
        if task.on_update: task.on_update()

        # ── Metadata theo tập + SRT tổng hợp ─────────────────────────
        episode_ranges = []
        merged_srt_lines = []
        srt_offset = 0.0
        cue_index = 0
        for ep, full in pairs:
            try:
                dur = get_video_duration(full)
            except Exception:
                dur = 0.0
            ep_label = ep.get('filename') or ep.get('id', '')
            srt_url = ep.get('srt_url') or ''
            if srt_url.startswith('/output/'):
                srt_rel = srt_url.split('/output/', 1)[-1].replace('/', os.sep)
                srt_full = os.path.abspath(os.path.join(OUTPUT_DIR, srt_rel))
                if srt_full.startswith(os.path.abspath(OUTPUT_DIR) + os.sep) and os.path.isfile(srt_full):
                    try:
                        with open(srt_full, 'r', encoding='utf-8-sig') as f:
                            for block in f.read().split('\n\n'):
                                if '-->' not in block:
                                    continue
                                lines = [l for l in block.splitlines() if l.strip()]
                                tl = next((l for l in lines if '-->' in l), None)
                                if not tl:
                                    continue
                                m = re.match(r'(\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)\s*-->\s*(\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?)', tl.strip())
                                if not m:
                                    continue
                                s = time_to_seconds(m.group(1))
                                e = time_to_seconds(m.group(2))
                                tl_idx = lines.index(tl)
                                text = ' '.join(lines[tl_idx + 1:]).strip()
                                cue_index += 1
                                merged_srt_lines.append(
                                    f'{cue_index}\n{seconds_to_time_short(s + srt_offset)} --> {seconds_to_time_short(e + srt_offset)}\n{text}'
                                )
                    except Exception:
                        pass
            episode_ranges.append({
                'episode_id': ep.get('id'),
                'filename': ep_label,
                'start_time': round(srt_offset, 3),
                'end_time': round(srt_offset + dur, 3),
                'duration': round(dur, 3),
                'video_url': ep.get('result_url'),
                'srt_url': srt_url or None,
            })
            srt_offset += dur
        task.progress = 90
        task.message = 'Đang lưu phụ đề & metadata...'
        if task.on_update: task.on_update()

        rec = {
            'project_id': project_id,
            'source_count': len(paths),
            'episode_ids': [e.get('id') for e, _ in pairs],
            'video_url': f'/media/{os.path.relpath(out, OUTPUT_DIR).replace(chr(92), "/")}',
            'created_at': datetime.now().isoformat(),
        }
        srt_out = os.path.join(FINAL_DIR, base_out + '.srt')
        if merged_srt_lines:
            with open(srt_out, 'w', encoding='utf-8') as f:
                f.write('\n\n'.join(merged_srt_lines) + '\n')
            rec['srt_url'] = f'/output/{os.path.relpath(srt_out, OUTPUT_DIR).replace(chr(92), "/")}'
        rec['episode_ranges'] = episode_ranges
        rec['total_duration'] = round(srt_offset, 3)

        meta_out = os.path.join(FINAL_DIR, base_out + '.merge.json')
        with open(meta_out, 'w', encoding='utf-8') as f:
            json.dump({
                'project_id': project_id,
                'project_name': p.get('name'),
                'video_url': rec['video_url'],
                'srt_url': rec.get('srt_url'),
                'episode_ranges': episode_ranges,
                'total_duration': rec['total_duration'],
            }, f, ensure_ascii=False, indent=2)

        # Lưu bản ghi ghép gần nhất vào project (không đè episodes)
        database.update_project(project_id, settings={**p.get('settings', {}), 'last_merge': rec})
        task.result = rec
        task.progress = 100
        task.message = 'Hoàn tất ghép video!'
        if task.on_update: task.on_update()

    task = task_manager.create_task(paths[0], {'type': 'merge', 'project_id': project_id})
    task_manager.run_task(task, _run_merge)
    return {'task_id': task.id, 'status': task.status}


@router.post('/api/projects/{project_id}/episodes')
async def add_episodes(
    project_id: str,
    files: list[UploadFile] = File(...),
    voice_id: str = Form(''),
    style: str = Form(''),
    model: str = Form(''),
    mode: str = Form('api'),
    detail: str = Form(''),
    custom_minutes: str = Form(''),
    edit_mode: str = Form(''),
    fx_flip: str = Form(''),
    fx_zoom: str = Form(''),
    fx_speed: str = Form(''),
    fx_reverse: str = Form(''),
    character_name_mode: str = Form(''),
    free_order: str = Form('')
):
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')

    episodes = []
    for file in files:
        path = os.path.join(UPLOAD_DIR, f'{int(time.time())}_{file.filename}')
        with open(path, 'wb') as f:
            shutil.copyfileobj(file.file, f)

        # Lưu giá trị NGUYÊN BẢN từ form: ô trống = thừa kế series settings
        # (được điền khi chạy qua _effective_options), giá trị do người dùng
        # chọn riêng cho tập sẽ được tôn trọng không bị ghi đè.
        options = {
            'voice_id': voice_id.strip(),
            'style':    style.strip(),
            'model':    model.strip(),
            'mode':     mode,
            'detail':   detail.strip(),
            'custom_minutes': custom_minutes.strip(),
            'edit_mode': edit_mode.strip(),
            'character_name_mode': character_name_mode.strip(),
            'fx_flip':      fx_flip.strip(),
            'fx_zoom':      fx_zoom.strip(),
            'fx_speed':     fx_speed.strip(),
            'fx_reverse':   fx_reverse.strip(),
            'free_order':   free_order.strip(),
        }
        ep = database.add_episode_to_project(project_id, file.filename, path, options)
        episodes.append(ep)

    return {'episodes': episodes}


@router.post('/api/projects/{project_id}/episodes/{episode_id}/process')
async def process_episode(project_id: str, episode_id: str):
    """Chạy xử lý một tập đơn lẻ (API mode)."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    if (ep.get('options') or {}).get('mode') == 'manual':
        raise HTTPException(400, 'Tập manual cần dùng manual-prepare trước')
    if ep['status'] in ('running', 'queueing'):
        raise HTTPException(400, 'Tập đang chạy')
    old_task_id = ep.get('task_id')
    if old_task_id:
        task_manager.force_cancel(old_task_id)
    t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))
    t.on_update = _episode_updater(project_id, episode_id, t)
    database.update_episode(project_id, episode_id, {
        'status': 'queueing', 'message': 'Đã đưa vào hàng đợi', 'task_id': t.id,
        'error': None, 'progress': 0,
    })
    task_manager.run_task(t, process_pipeline)
    return {'ok': True, 'task_id': t.id}


@router.post('/api/projects/{project_id}/process')
async def process_project(project_id: str):
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')

    enqueued = 0
    for ep in p.get('episodes', []):
        # Manual episodes không đi qua "Process all" — chúng cần bước tạo prompt
        # rồi submit kịch bản riêng (manual-prepare / manual-submit).
        if ep['status'] in ['pending', 'failed', 'cancelled'] and (ep.get('options') or {}).get('mode') != 'manual':
            t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))

            t.on_update = _episode_updater(project_id, ep['id'], t)
            database.update_episode(project_id, ep['id'], {'status': 'queueing', 'message': 'Đã đưa vào hàng đợi', 'task_id': t.id})
            task_manager.run_task(t, process_pipeline)
            enqueued += 1

    return {'enqueued': enqueued}


@router.delete('/api/projects/{project_id}')
async def delete_project(project_id: str):
    """Xóa toàn bộ dự án: hủy mọi task, xóa sạch video thành phẩm trong Thư viện, xóa video gốc upload và xóa DB."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')

    # 1. Hủy task đang chạy & xóa toàn bộ file liên quan của từng tập
    # (video đầu ra + SRT, video nén manual + cache studio, video gốc upload, temp work)
    for ep in p.get('episodes', []):
        task_id = ep.get('task_id')
        if task_id:
            task_manager.force_cancel(task_id)
        _delete_episode_related_files(ep)

    # 2. Xóa video ghép nối (merged) của dự án này trong Thư viện (FINAL_DIR)
    try:
        if os.path.isdir(FINAL_DIR):
            for fn in os.listdir(FINAL_DIR):
                if fn.endswith('.merge.json'):
                    meta_path = os.path.join(FINAL_DIR, fn)
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        if meta.get('project_id') == project_id:
                            base_m = fn[:-11]  # Bỏ đuôi .merge.json
                            for ext in ('', '.mp4', '.srt', '.mkv', '.webm', '.merge.json'):
                                f_to_del = os.path.join(FINAL_DIR, (base_m if ext == '' else base_m + ext))
                                if os.path.isfile(f_to_del):
                                    try: os.remove(f_to_del)
                                    except Exception: pass
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Xóa giọng mẫu clone (nếu có) của dự án
    try:
        for ext in ('.wav', '.txt'):
            cand = os.path.join(VOICE_REF_DIR, project_id + ext)
            if os.path.isfile(cand):
                try: os.remove(cand)
                except Exception: pass
    except Exception:
        pass

    success = database.delete_project(project_id)
    if not success:
        raise HTTPException(404, 'Không tìm thấy dự án')
    return {'ok': True}


@router.put('/api/projects/{project_id}')
async def update_project(project_id: str, name: str = Form(None), settings: str = Form(None)):
    """Đổi tên dự án hoặc cập nhật settings mặc định."""
    import json as _json
    parsed_settings = None
    if settings:
        try:
            parsed_settings = _json.loads(settings)
        except Exception:
            raise HTTPException(400, 'settings phải là JSON hợp lệ')
    p = database.update_project(project_id, name=name, settings=parsed_settings)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    return p


@router.post('/api/projects/{project_id}/episodes/{episode_id}/suggest-characters')
async def suggest_characters(project_id: str, episode_id: str, force: bool = Query(False)):
    """Tự phát hiện nhân vật từ kịch bản của tập đã có lời bình (gọi Gemini chỉ-text,
    không dùng video). Trả danh sách gợi ý [{name, aliases}] VÀ GHI luôn vào
    episode_characters (nguồn registry cho các tập SAU nếu tập này chưa xét).
    Trích lại bằng AI KHÔNG đánh dấu đã xét (chỉ bấm Lưu duyệt mới tính).

    CACHE: kịch bản không đổi (narration_hash) → trả nguyên cache, không gọi AI.
    `force=true` (nút "Tạo lại nhân vật") → bỏ qua cache, gửi lại AI và ghi đè."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    narrations = [s.get('narration') for s in (ep.get('segments') or []) if ((s.get('narration') or '').strip())]
    if not narrations:
        raise HTTPException(400, 'Tập này chưa có kịch bản (lời bình) để trích nhân vật — hãy chạy tập trước')
    name_mode = ((ep.get('options') or {}).get('character_name_mode')
                 or (p.get('settings') or {}).get('character_name_mode')
                 or CHARACTER_NAME_MODE)
    script_text = '\n'.join(narrations)
    narration_hash = hashlib.sha1(script_text.encode('utf-8')).hexdigest()
    cached = database.get_episode_characters(project_id, episode_id)
    if cached and not force and database.get_episode_characters_hash(project_id, episode_id) == narration_hash:
        return {'characters': cached, 'name_mode': name_mode,
                'narration_count': len(narrations), 'cached': True}
    try:
        chars = extract_characters_from_script(script_text, name_mode)
    except Exception as e:
        raise HTTPException(502, f'Trích xuất nhân vật thất bại: {e}')
    database.save_episode_characters(project_id, episode_id, chars, narration_hash)
    return {'characters': chars, 'name_mode': name_mode,
            'narration_count': len(narrations), 'cached': False}


def _get_episode_character_name_mode(p, ep):
    return ((ep.get('options') or {}).get('character_name_mode')
            or (p.get('settings') or {}).get('character_name_mode')
            or CHARACTER_NAME_MODE)


def _sanitize_characters(characters):
    """Chuẩn hóa danh sách [{name, aliases}] — gộp lặp họ/tên, loại stopwords, dedupe theo tên lowercase, tên rõ 2–40 ký tự."""
    merged = {}
    for c in characters or []:
        if not isinstance(c, dict) or not c.get('name'):
            continue
        name = _collapse_doubled_prefix(c['name']).strip().strip('"“”')
        if not name or len(name) < 2 or len(name) > 40:
            continue
        if name.lower() in CHARACTER_STOPWORDS:
            continue
        raw_aliases = [_collapse_doubled_prefix(a) for a in (c.get('aliases') or []) if isinstance(a, str) and a.strip()]
        clean_aliases = []
        for a in raw_aliases:
            a = a.strip().strip('"“”')
            if not a or a.lower() == name.lower():
                continue
            if a.lower() in CHARACTER_STOPWORDS:
                continue
            if 2 <= len(a) <= 40:
                clean_aliases.append(a)
        clean_aliases = list(dict.fromkeys(clean_aliases))[:5]
        key = name.lower()
        if key in merged:
            merged[key]['aliases'] = list(dict.fromkeys(merged[key]['aliases'] + clean_aliases))[:5]
        else:
            merged[key] = {'name': name, 'aliases': clean_aliases}
    return list(merged.values())


@router.get('/api/projects/{project_id}/episodes/{episode_id}/characters')
async def episode_characters(project_id: str, episode_id: str):
    """Nhân vật đang lưu của TẬP (nguồn registry cho tập sau NẾU tập này chưa xét) —
    CHỈ ĐỌC, không gọi AI. Chưa có dữ liệu → trả mảng rỗng (không lỗi).
    `reviewed`: tập đã xét hay chưa (True → nhân vật riêng của tập KHÔNG gửi vào
    prompt các tập sau, chỉ còn bảng chung); `reviewed_auto`: True khi tự đánh dấu
    vì mọi nhân vật đã nằm trong bảng chung."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    narrations = [s.get('narration') for s in (ep.get('segments') or []) if ((s.get('narration') or '').strip())]
    flag = database.get_episode_characters_reviewed_flag(project_id, episode_id)
    reviewed = database.is_episode_characters_reviewed(project_id, episode_id, p.get('characters'))
    return {
        'characters': database.get_episode_characters(project_id, episode_id),
        'narration_count': len(narrations),
        'name_mode': _get_episode_character_name_mode(p, ep),
        'reviewed': reviewed,
        'reviewed_auto': reviewed and flag is None,
    }


@router.put('/api/projects/{project_id}/episodes/{episode_id}/characters')
async def save_episode_characters_endpoint(project_id: str, episode_id: str, characters: list = Body(...)):
    """Ghi đè danh sách nhân vật của 1 tập (sau khi sửa/chọn ở modal). Gửi [] = xóa
    nhân vật của tập. Giữ nguyên narration_hash để không phá cache kịch bản.
    Bấm Lưu ở modal duyệt = tập ĐÃ XÉT → đánh dấu reviewed để registry các tập sau
    chỉ còn bảng chung + nhân vật các tập chưa xét."""
    if not isinstance(characters, list):
        raise HTTPException(400, 'characters phải là một mảng')
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    clean = _sanitize_characters(characters)
    prev_hash = database.get_episode_characters_hash(project_id, episode_id)
    saved = database.save_episode_characters(project_id, episode_id, clean, prev_hash)
    database.set_episode_characters_reviewed(project_id, episode_id, True)
    return {'characters': saved, 'saved': len(saved), 'reviewed': True}


@router.put('/api/projects/{project_id}/episodes/{episode_id}/characters-reviewed')
async def set_episode_characters_reviewed_endpoint(project_id: str, episode_id: str, payload: dict = Body(...)):
    """Đánh dấu / bỏ xét nhân vật của 1 tập. Body {"reviewed": true/false}.
    reviewed=false (bỏ xét) → nhân vật riêng của tập được gửi lại vào prompt các tập sau."""
    if not isinstance(payload, dict) or not isinstance(payload.get('reviewed'), bool):
        raise HTTPException(400, 'Body phải là {"reviewed": true/false}')
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    database.set_episode_characters_reviewed(project_id, episode_id, payload['reviewed'])
    reviewed = database.is_episode_characters_reviewed(project_id, episode_id, p.get('characters'))
    return {'ok': True, 'reviewed': reviewed}


@router.get('/api/projects/{project_id}/episode-characters')
async def project_episode_characters(project_id: str):
    """Tổng hợp nhân vật đã cache theo TỪNG TẬP của cả dự án (nguồn: bảng episode_characters)."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    return {'episodes': database.get_project_episode_characters(project_id)}


@router.put('/api/projects/{project_id}/characters')
async def update_project_characters(project_id: str, characters: list = Body(...)):
    """THAY THẾ toàn bộ danh sách nhân vật của project theo REST PUT. Gửi [] = xóa sạch."""
    if not isinstance(characters, list):
        raise HTTPException(400, 'characters phải là một mảng')
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    clean = _sanitize_characters(characters)
    saved = database.update_project(project_id, characters=clean)
    if not saved:
        raise HTTPException(404, 'Không tìm thấy dự án')
    return saved


@router.post('/api/projects/{project_id}/characters/sync-scripts')
async def sync_characters_to_scripts(project_id: str):
    """Đồng bộ ngược: Chuẩn hóa tên nhân vật (canonical + aliases) vào kịch bản (segments)
    và phụ đề SRT của TẤT CẢ các tập đã có kịch bản trong dự án.

    Ưu tiên nguồn nhân vật cho từng tập:
    1. episode_characters của tập đó (nơi người dùng đã chốt và lưu) — ưu tiên cao nhất.
    2. project.characters (danh sách chung) — bổ sung tên chưa có trong episode_characters.
    Nếu tập không có episode_characters → dùng thuần project.characters."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    project_chars = p.get('characters') or []

    updated_episodes = 0
    updated_segments_count = 0

    for ep in p.get('episodes') or []:
        eid = ep.get('id')
        segs = ep.get('segments') or []
        if not segs:
            continue

        # Xây bảng nhân vật áp dụng cho tập này:
        # episode_characters (đã chốt) ưu tiên cao hơn project.characters.
        ep_chars = database.get_episode_characters(project_id, eid) or []
        if ep_chars:
            # Merge: ep_chars trước, bổ sung project_chars (những tên chưa có trong tập)
            seen_names = {c['name'].lower() for c in ep_chars}
            chars_for_ep = list(ep_chars)
            for pc in project_chars:
                if (pc.get('name') or '').lower() not in seen_names:
                    chars_for_ep.append(pc)
        else:
            # Tập chưa có episode_characters → dùng project.characters
            chars_for_ep = project_chars

        if not chars_for_ep:
            continue

        ep_changed = False
        new_segs = []
        for s in segs:
            s_dict = dict(s)
            old_narr = s_dict.get('narration') or ''
            new_narr = normalize_character_names(old_narr, chars_for_ep)
            if new_narr != old_narr:
                s_dict['narration'] = new_narr
                ep_changed = True
                updated_segments_count += 1
            new_segs.append(s_dict)

        if ep_changed:
            updated_episodes += 1
            # Cập nhật lại SQLite segments
            database.update_episode(project_id, eid, {'segments': new_segs})
            # Nếu đã có file SRT, cập nhật lại file SRT trên đĩa
            srt_url = ep.get('srt_url')
            if srt_url:
                try:
                    rel_path = srt_url.replace('/output/', '').replace('/', os.sep)
                    full_srt = os.path.join(OUTPUT_DIR, rel_path)
                    if os.path.isfile(full_srt):
                        create_srt(new_segs, full_srt)
                except Exception as e:
                    logger.warning(f"[SYNC-CHAR] Cập nhật SRT tập {eid} thất bại: {e}")

    return {
        'ok': True,
        'updated_episodes': updated_episodes,
        'updated_segments': updated_segments_count,
        'message': f'Đã chuẩn hóa tên nhân vật cho {updated_episodes} tập phim ({updated_segments_count} phân cảnh).'
    }


# ── Episode Management ─────────────────────────────────────────

@router.delete('/api/projects/{project_id}/episodes/{episode_id}')
async def delete_episode(project_id: str, episode_id: str):
    """Xóa một tập phim — tự động hủy task, xóa toàn bộ file liên quan
    (video đầu ra + SRT, video nén manual + cache studio, video gốc upload, temp work)."""
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')

    task_id = ep.get('task_id')
    if task_id:
        task_manager.force_cancel(task_id)

    counts = _delete_episode_related_files(ep)

    ok = database.delete_episode(project_id, episode_id)
    if not ok:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    return {'ok': True, 'deleted_files': counts}


@router.post('/api/projects/{project_id}/episodes/{episode_id}/cancel')
async def cancel_episode(project_id: str, episode_id: str):
    """Hủy xử lý tập phim đang chạy hoặc đang chờ."""
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    task_id = ep.get('task_id')
    if task_id:
        task_manager.force_cancel(task_id)
    database.update_episode(project_id, episode_id, {
        'status': 'cancelled',
        'message': 'Đã hủy bởi người dùng'
    })
    return {'ok': True}


@router.post('/api/projects/{project_id}/episodes/{episode_id}/retry')
async def retry_episode(project_id: str, episode_id: str):
    """Chạy lại tập bị lỗi hoặc đặt lại về pending."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    # Rerun = làm lại NHƯ MỘT TẬP MỚI: xóa cả file output cũ trên đĩa (output/final)
    # của tập này trước khi chạy lại, tránh tích lũy file cũ và gây nhầm library.
    _delete_episode_outputs(ep)
    # Hủy task cũ (nếu còn đang chạy/quêu) trước khi tạo task mới — tránh 2 task chạy ĐỒNG THỜI
    # trên cùng 1 tập, gây trùng tiến độ + đè file trung gian.
    old_task_id = (ep or {}).get('task_id')
    if old_task_id:
        task_manager.force_cancel(old_task_id)
    # Rerun = chạy lại TỪ ĐẦU như một tập mới. Tập manual GIỮ NGUYÊN chế độ thủ công:
    # không đổi sang auto — chuyển hướng sang flow manual-run (nén + prompt mới + AI Studio).
    mode = (ep.get('options') or {}).get('mode')
    if mode == 'manual':
        # reset DB trước để manual_run_episode không chặn do status cũ vẫn running/queueing
        # (force_cancel khi task đang running chỉ set cờ, không cập nhật DB).
        database.reset_episode(project_id, episode_id)
        return await manual_run_episode(project_id, episode_id)
    # Reset về pending, tạo task mới và queue — dùng setting series HIỆN TẠI (pending & chạy lại lấy setting mới)
    database.reset_episode(project_id, episode_id)
    t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))

    t.on_update = _episode_updater(project_id, episode_id, t)
    database.update_episode(project_id, episode_id, {'status': 'queueing', 'message': 'Đã đưa vào hàng đợi để retry', 'task_id': t.id})
    task_manager.run_task(t, process_pipeline)
    return {'ok': True, 'task_id': t.id}


# ── Manual mode cho Series ──────────────────────────────────────

@router.post('/api/projects/{project_id}/episodes/{episode_id}/manual-prepare')
async def manual_prepare_episode(project_id: str, episode_id: str):
    """Chuẩn bị tập thủ công: nén video + dựng prompt, đợi người dùng dán kịch bản.

    Không chạy pipeline — kết quả trả về {task_id, prompt, compressed_url, ...}."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    if (ep.get('options') or {}).get('mode') != 'manual':
        raise HTTPException(400, 'Tập này không ở chế độ thủ công (manual)')
    if ep.get('status') in ('running', 'queueing'):
        raise HTTPException(400, 'Tập đang chạy, không thể tạo lại prompt')

    t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))
    data = _setup_manual_task(t)
    database.update_episode(project_id, episode_id, {
        'task_id':                t.id,
        'status':                 'awaiting_result',
        'progress':               0,
        'message':                'Đang chờ bạn dán kịch bản AI',
        'error':                  None,
        'manual_prompt':          t.prompt,
        'manual_result':          None,
        'manual_compressed_url':  data['compressed_url'],
        'num_segments':           data['num_segments'],
        'target_words':           data['target_words'],
    })
    return data


@router.post('/api/projects/{project_id}/episodes/{episode_id}/manual-run')
async def manual_run_episode(project_id: str, episode_id: str):
    """Chạy NGAY tập thủ công bằng một nút (giống nút Run của mode API):
    nén video + dựng prompt, rồi TỰ ĐỘNG điều khiển Google AI Studio trên Chrome thật
    lấy kịch bản → submit → render, không cần người dùng dán tay."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    if (ep.get('options') or {}).get('mode') != 'manual':
        raise HTTPException(400, 'Tập này không ở chế độ thủ công (manual)')
    if ep.get('status') in ('running', 'queueing'):
        raise HTTPException(400, 'Tập đang chạy, không thể chạy lại')

    old_task_id = ep.get('task_id')
    if old_task_id:
        task_manager.force_cancel(old_task_id)

    t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))
    t.on_update = _episode_updater(project_id, episode_id, t)
    # Dựng prompt NGAY (không nén đồng bộ) để trả response nhanh, UI chuyển tranh tiến trình.
    # Việc NÉN (file + bản ≤ngưỡng) do thread _run_ai_studio_auto lo — nén xong mới mở studio.
    data = _prepare_manual_prompt(t)
    database.update_episode(project_id, episode_id, {
        'task_id':               t.id,
        'status':                'running',
        'progress':              20,
        'message':               'Đang chuẩn bị video nén...',
        'error':                 None,
        'manual_prompt':         t.prompt,
        'manual_result':         None,
        'manual_compressed_url': data['compressed_url'],
        'num_segments':          data['num_segments'],
        'target_words':          data['target_words'],
    })
    t.status = 'running'
    t.message = 'Đang chuẩn bị video nén...'
    threading.Thread(target=lambda: _run_ai_studio_auto(t), daemon=True).start()
    return {'ok': True, 'task_id': t.id}


@router.post('/api/projects/{project_id}/episodes/{episode_id}/manual-submit')
async def manual_submit_episode(project_id: str, episode_id: str, result_text: str = Form(...)):
    """Nhận kịch bản AI dán vào tập thủ công rồi chạy pipeline tạo video."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    if (ep.get('options') or {}).get('mode') != 'manual':
        raise HTTPException(400, 'Tập này không ở chế độ thủ công (manual)')

    # Tái dùng task đã prepare (giữ task_id ổn định); nếu server restart mất task
    # thì tạo mới — pipeline manual không cần compressed_path, chỉ cần result_text.
    t = task_manager.get_task(ep.get('task_id'))
    if not t:
        t = task_manager.create_task(ep['video_path'], _effective_options(ep, p))
    t.result_text = result_text
    t.on_update = _episode_updater(project_id, episode_id, t)
    database.update_episode(project_id, episode_id, {
        'status':        'queueing',
        'message':       'Đã nhận kịch bản, bắt đầu tạo video...',
        'error':         None,
        'manual_result': result_text,
    })
    task_manager.run_task(t, process_pipeline)
    return {'task_id': t.id}


@router.post('/api/projects/{project_id}/episodes/{episode_id}/manual-folder')
async def manual_episode_folder(project_id: str, episode_id: str):
    """Mở thư mục chứa video nén thủ công (output/manual) cho tập này."""
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    os.makedirs(MANUAL_DIR, exist_ok=True)
    try:
        os.startfile(MANUAL_DIR)
    except Exception as e:
        raise HTTPException(500, f'Không mở được thư mục: {e}')
    return {'ok': True, 'folder': MANUAL_DIR}


@router.put('/api/projects/{project_id}/episodes/{episode_id}/options')
async def update_episode_options(
    project_id: str,
    episode_id: str,
    mode:     str = Form(None),
    voice_id: str = Form(None),
    model:    str = Form(None),
    style:    str = Form(None),
    detail:   str = Form(None),
    custom_minutes: str = Form(None),
    edit_mode: str = Form(None),
    fx_flip: str = Form(None),
    fx_zoom: str = Form(None),
    fx_speed: str = Form(None),
    fx_reverse: str = Form(None),
    character_name_mode: str = Form(None),
    free_order: str = Form(None),
):
    """Cập nhật tùy chọn xử lý của một tập (trước khi chạy)."""
    ep = database.get_episode(project_id, episode_id)
    if not ep:
        raise HTTPException(404, 'Không tìm thấy tập phim')
    if ep['status'] in ('running', 'queueing'):
        raise HTTPException(400, 'Không thể thay đổi tùy chọn khi tập đang chạy')
    new_opts = dict(ep.get('options', {}))
    if mode     is not None: new_opts['mode']     = mode
    if voice_id is not None: new_opts['voice_id'] = voice_id
    if model    is not None: new_opts['model']    = model
    if style    is not None: new_opts['style']    = style
    if detail   is not None: new_opts['detail']   = detail
    if custom_minutes is not None: new_opts['custom_minutes'] = custom_minutes
    if edit_mode is not None: new_opts['edit_mode'] = edit_mode
    if character_name_mode is not None: new_opts['character_name_mode'] = character_name_mode
    if fx_flip    is not None: new_opts['fx_flip']    = fx_flip
    if fx_zoom    is not None: new_opts['fx_zoom']    = fx_zoom
    if fx_speed   is not None: new_opts['fx_speed']   = fx_speed
    if fx_reverse is not None: new_opts['fx_reverse'] = fx_reverse
    if free_order is not None: new_opts['free_order'] = free_order
    updated = database.update_episode(project_id, episode_id, {'options': new_opts})
    return updated
