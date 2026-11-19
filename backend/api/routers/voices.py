"""Router: giọng mẫu clone theo dự án + thư viện giọng custom (VoiceStudio)."""
import os, shutil, json, secrets
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, Form, HTTPException

from backend.core.config import VOICE_REF_DIR, VOICES, LOCAL_HARDWARE_LOCK
from backend.core import database

router = APIRouter()

VOICE_REGISTRY_FILE = os.path.join(VOICE_REF_DIR, 'voicestudio_voices.json')


def _read_custom_registry() -> list:
    try:
        if os.path.isfile(VOICE_REGISTRY_FILE):
            with open(VOICE_REGISTRY_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _write_custom_registry(items: list):
    os.makedirs(VOICE_REF_DIR, exist_ok=True)
    with open(VOICE_REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


@router.post('/api/projects/{project_id}/voice-ref')
async def upload_voice_ref(project_id: str, file: UploadFile = File(...), ref_text: str = Form('')):
    """Upload giọng mẫu tiếng Việt (3-12s, wav/mp3/m4a/ogg) cho dự án."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.wav', '.mp3', '.m4a', '.ogg', '.flac', '.opus'):
        raise HTTPException(400, 'File mẫu phải là audio (wav/mp3/m4a/ogg/flac/opus)')
    os.makedirs(VOICE_REF_DIR, exist_ok=True)
    tmp_in = os.path.join(VOICE_REF_DIR, f'{project_id}.upload{ext}')
    out_wav = os.path.join(VOICE_REF_DIR, f'{project_id}.wav')
    with open(tmp_in, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    try:
        import subprocess as _sp
        with LOCAL_HARDWARE_LOCK:
            r = _sp.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp_in,
                         '-t', '12', '-ar', '24000', '-ac', '1',
                         out_wav],
                        capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out_wav):
            raise RuntimeError((r.stderr or '')[:300] or 'ffmpeg chuẩn hóa thất bại')
        with LOCAL_HARDWARE_LOCK:
            d = _sp.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', out_wav],
                        capture_output=True, text=True)
            dur = float((d.stdout or '').strip() or 0)
        if dur < 2.0:
            try: os.remove(out_wav)
            except OSError: pass
            raise HTTPException(400, f'Mẫu quá ngắn ({dur:.1f}s) — cần ít nhất 2s, tốt nhất 3-10s')
    finally:
        try: os.remove(tmp_in)
        except OSError: pass

    clean_text = (ref_text or '').strip()
    txt_path = os.path.splitext(out_wav)[0] + '.txt'
    if clean_text:
        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(clean_text)
        except OSError:
            pass

    # Nếu VoiceStudio đang chạy, đồng bộ tạo profile mới
    try:
        from backend.services.voicestudio_service import create_profile
        create_profile(f'Project_{project_id[:8]}', out_wav, ref_text=clean_text)
    except Exception:
        pass

    settings = dict(p.get('settings') or {})
    settings['tts_ref_audio'] = os.path.abspath(out_wav)
    settings['tts_ref_text'] = clean_text
    database.update_project(project_id, settings=settings)
    return {'ok': True, 'ref_audio': settings['tts_ref_audio'],
            'duration': round(dur, 1), 'has_text': bool(clean_text)}


@router.delete('/api/projects/{project_id}/voice-ref')
async def delete_voice_ref(project_id: str):
    """Xóa giọng mẫu của dự án."""
    p = database.get_project(project_id)
    if not p:
        raise HTTPException(404, 'Không tìm thấy dự án')
    base = os.path.join(VOICE_REF_DIR, project_id)
    for cand in (base + '.wav', base + '.txt'):
        try:
            if os.path.isfile(cand):
                os.remove(cand)
        except OSError:
            pass
    settings = dict(p.get('settings') or {})
    settings.pop('tts_ref_audio', None)
    settings.pop('tts_ref_text', None)
    database.update_project(project_id, settings=settings)
    return {'ok': True}


@router.post('/api/voices/custom')
async def add_custom_voice(name: str = Form(''), file: UploadFile = File(...), ref_text: str = Form('')):
    """Thêm giọng VoiceStudio clone vào thư viện."""
    clean_name = (name or '').strip()[:40]
    if not clean_name:
        raise HTTPException(400, 'Cần đặt tên cho giọng (vd "Giọng mẫu 1")')
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.wav', '.mp3', '.m4a', '.ogg', '.flac', '.opus'):
        raise HTTPException(400, 'File mẫu phải là audio (wav/mp3/m4a/ogg/flac/opus)')
    vid = secrets.token_hex(3)
    os.makedirs(VOICE_REF_DIR, exist_ok=True)
    tmp_in = os.path.join(VOICE_REF_DIR, f'custom_{vid}.upload{ext}')
    out_wav = os.path.join(VOICE_REF_DIR, f'custom_{vid}.wav')
    with open(tmp_in, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    try:
        import subprocess as _sp
        with LOCAL_HARDWARE_LOCK:
            r = _sp.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp_in,
                         '-t', '12', '-ar', '24000', '-ac', '1',
                         out_wav],
                        capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(out_wav):
            raise RuntimeError((r.stderr or '')[:300] or 'ffmpeg chuẩn hóa thất bại')
        with LOCAL_HARDWARE_LOCK:
            d = _sp.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', out_wav],
                        capture_output=True, text=True)
            dur = float((d.stdout or '').strip() or 0)
        if dur < 2.0:
            try: os.remove(out_wav)
            except OSError: pass
            raise HTTPException(400, f'Mẫu quá ngắn ({dur:.1f}s) — cần ít nhất 2s, tốt nhất 3-10s')
    finally:
        try: os.remove(tmp_in)
        except OSError: pass

    clean_text = (ref_text or '').strip()
    vs_profile_id = vid
    try:
        from backend.services.voicestudio_service import create_profile
        res = create_profile(clean_name, out_wav, ref_text=clean_text)
        if isinstance(res, dict) and ('id' in res or 'profile_id' in res):
            vs_profile_id = res.get('id') or res.get('profile_id')
    except Exception:
        pass

    voice_key = f'vs_custom_{vid}'
    VOICES[voice_key] = {
        'name': f'VoiceStudio - {clean_name}',
        'type': 'voicestudio',
        'id': vs_profile_id,
        'custom': True,
    }
    items = _read_custom_registry()
    items.append({'id': vid, 'name': clean_name, 'profile_id': vs_profile_id,
                  'ref_audio': os.path.abspath(out_wav), 'ref_text': clean_text,
                  'created_at': datetime.now().isoformat()})
    _write_custom_registry(items)
    return {'ok': True, 'voice_key': voice_key, 'name': clean_name,
            'duration': round(dur, 1), 'has_text': bool(clean_text)}


@router.delete('/api/voices/custom/{vid}')
async def delete_custom_voice(vid: str):
    """Xóa 1 giọng custom."""
    items = _read_custom_registry()
    hit = next((it for it in items if str(it.get('id')) == vid), None)
    if not hit:
        raise HTTPException(404, 'Không tìm thấy giọng này')
    base = os.path.splitext(hit.get('ref_audio') or '')[0]
    for cand in (base + '.wav', base + '.txt'):
        try:
            if cand and os.path.isfile(cand):
                os.remove(cand)
        except OSError:
            pass
    items = [it for it in items if str(it.get('id')) != vid]
    _write_custom_registry(items)
    VOICES.pop(f'vs_custom_{vid}', None)
    return {'ok': True}
