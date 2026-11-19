"""Hạ tầng & helper dùng chung cho các API router (tách ra từ backend/main.py).

Chứa: logger, cache ngắn hạn, trạng thái heartbeat/auto-shutdown, và các helper
nghiệp vụ chia sẻ giữa nhiều router (tính target, options hiệu dụng, updater tiến độ,
đường dẫn video nén thủ công, dọn file output...)."""
import os, shutil, time, threading, re, json, secrets, hashlib, logging
from datetime import datetime

from backend.core.config import *
from backend.core.task_manager import task_manager, Task, _segment_dict
from backend.core import key_pool
from backend.core import database
from backend.utils.srt_parser import (
    parse_segments, calculate_speed_adjustment, resolve_overlaps, time_to_seconds,
)
from backend.services.gemini_service import (
    summarize_video, build_scene_prompt, parse_result_text,
    extract_characters_from_script, _collapse_doubled_prefix,
    normalize_character_names, CHARACTER_STOPWORDS,
)
from backend.services.tts_service import generate_all_tts, preview_voice as _preview_voice
from backend.services.video_service import (
    get_real_video_duration,
    get_video_duration,
    compress_video_for_upload,
    render_smart_shot,
    cut_merge_all_segments,
    concat_videos,
    create_srt,
    make_studio_upload_copy,
    ffmpeg_cancel_context,
    detect_shots,
    merge_all_segments,
)
from backend.services.ai_studio_bridge import (
    run_ai_studio_auto,
    get_ai_studio_account_info,
    open_login_browser,
    close_automation_browser,
)
from backend.core.logger import init_logging, read_logs, clear_logs

logger = logging.getLogger('backend.main')

# Tag đánh dấu file nén API (nén nhẹ, bỏ audio) — để không tái dùng nhầm file cũ ~90MB
# (khớp theo prefix base). File manual giữ nguyên không tag, loại trừ tag này khi tái dùng.
MANUAL_COMPRESS_TAG = '_sm'

# ── Cache ngắn hạn cho endpoint có lời gọi mạng nặng (tránh chặn event loop khi UI poll) ──
_response_cache: dict = {}
_response_cache_lock = threading.Lock()

def _cache_get(key: str, ttl: float):
    with _response_cache_lock:
        item = _response_cache.get(key)
    if not item:
        return None
    value, ts = item
    return value if (time.time() - ts) <= ttl else None

def _cache_set(key: str, value):
    with _response_cache_lock:
        _response_cache[key] = (value, time.time())

# ── Tự động tắt server khi không truy cập sau 5 phút (Auto-Shutdown on Idle) ──
_last_heartbeat_time = time.time()
_heartbeat_lock = threading.Lock()
AUTO_SHUTDOWN_TIMEOUT_SEC = 300  # 5 phút (300s)

def touch_heartbeat():
    """Cập nhật mốc thời gian truy cập cuối cùng (gọi từ middleware + endpoint heartbeat)."""
    global _last_heartbeat_time
    with _heartbeat_lock:
        _last_heartbeat_time = time.time()

def heartbeat_idle_seconds() -> float:
    with _heartbeat_lock:
        return time.time() - _last_heartbeat_time

def is_server_busy() -> bool:
    """Kiểm tra xem hệ thống có đang bận xử lý task hoặc render video hay không."""
    try:
        with task_manager._lock:
            if any(t.status in ('pending', 'running') for t in task_manager.tasks.values()):
                return True
        if not task_manager.worker_queue.empty():
            return True
    except Exception:
        pass
    try:
        from backend.core.db_engine import get_db_cursor
        with get_db_cursor(commit=False) as cur:
            row = cur.execute("SELECT COUNT(*) as cnt FROM episodes WHERE status IN ('queueing', 'running')").fetchone()
            if row and row['cnt'] > 0:
                return True
    except Exception:
        pass
    return False


def _compute_targets(options, video_duration=0):
    """Tính số phân đoạn + tổng số từ + thời lượng mục tiêu.

    - TỔNG SỐ TỪ & THỜI LƯỢNG video tóm tắt: theo độ chi tiết người dùng chọn.
    - SỐ PHÂN ĐOẠN: theo video GỐC (~20s/cảnh) để AI phủ đều toàn bộ cốt truyện.
      Thời lượng tóm tắt cuối = Σ TTS duration ~ target_words / 4.62 wps (tốc độ đo thực).
    """
    detail = options.get('detail', DEFAULT_DETAIL)
    if detail == 'custom':
        # Độ chi tiết TÙY CHỈNH: người dùng tự nhập số phút mong muốn (1–60).
        try:
            minutes = float(options.get('custom_minutes') or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        if not 1 <= minutes <= 60:
            minutes = DETAIL_LEVELS[DEFAULT_DETAIL]['target_sec'] / 60
        target_sec = int(round(minutes * 60))
        target_words = max(1, int(round(minutes * WORDS_PER_MINUTE)))
    else:
        level = DETAIL_LEVELS.get(detail, DETAIL_LEVELS[DEFAULT_DETAIL])
        target_sec = level.get('target_sec', (level['min_sec'] + level['max_sec']) // 2)
        minutes = target_sec / 60
        # target_words ưu tiên giá trị LÀM TRÒN cố định trong DETAIL_LEVELS (1500/2000/2500);
        # nếu chưa khai báo thì tính từ tốc độ đọc TTS đo thực.
        target_words = level.get('target_words') or max(1, int(round(minutes * WORDS_PER_MINUTE)))
    if video_duration and video_duration > 0:
        num_segments = max(5, int(round(video_duration / 20)))
    else:
        num_segments = max(5, int(round(minutes * SEGMENTS_PER_MINUTE)))
    return target_words, num_segments, target_sec


def _auto_character_registry(project_id: str, approved: list) -> list:
    """Registry mặc định cho các tập tiếp theo = NHÂN VẬT ĐÃ DUYỆT ở bảng chung (approved,
    ưu tiên khi trùng tên) + nhân vật tự trích của các tập CHƯA XÉT (bảng episode_characters).

    Tập ĐÃ XÉT (người dùng bấm Lưu duyệt, hoặc cache của nó đã nằm hết trong bảng chung)
    bị LOẠI khỏi registry để prompt gọn và không gửi tên rác/thừa cho AI.
    Tự động lọc bỏ các stopwords và tên rác để prompt đưa vào AI luôn sạch sẽ."""
    registry = []
    seen = set()
    for c in (approved or []):
        name = (c.get('name') or '').strip()
        if not name or len(name) < 2 or name.lower() in seen or name.lower() in CHARACTER_STOPWORDS:
            continue
        seen.add(name.lower())
        registry.append(c)
    try:
        reviewed_ids = database.get_reviewed_episode_ids(project_id, approved)
    except Exception:
        reviewed_ids = set()
    for ep in database.get_project_episode_characters(project_id):
        if ep.get('episode_id') in reviewed_ids or ep.get('reviewed'):
            continue
        for c in (ep.get('characters') or []):
            name = (c.get('name') or '').strip()
            if not name or len(name) < 2 or name.lower() in seen or name.lower() in CHARACTER_STOPWORDS:
                continue
            seen.add(name.lower())
            registry.append(c)
    return registry


def _effective_options(ep, project):
    """Options cho TẬP CHẠY MỚI / CHẠY LẠI.

    Series settings là MẶC ĐỊNH: chỉ điền vào các khóa tập còn TRỐNG
    (voice_id, style, model, detail). Giá trị người dùng chọn riêng cho tập
    (lúc thêm tập hoặc qua update-options) được GIỮ NGUYÊN để override thật sự
    có hiệu lực; 'mode' luôn giữ riêng của tập."""
    options = dict(ep.get('options') or {})
    settings = project.get('settings') or {}
    for k in ('voice_id', 'style', 'model', 'detail', 'custom_minutes', 'edit_mode', 'character_name_mode', 'free_order', 'tts_ref_audio', 'tts_ref_text'):
        if not options.get(k) and settings.get(k):
            options[k] = settings[k]
    if not options.get('characters'):
        combined = _auto_character_registry(project.get('id') or '', project.get('characters'))
        if combined:
            options['characters'] = combined
        elif CHARACTER_REGISTRY:
            options['characters'] = CHARACTER_REGISTRY
    if not options.get('edit_mode'):
        options.setdefault('edit_mode', EDIT_MODE_DEFAULT)
    if not options.get('character_name_mode'):
        options.setdefault('character_name_mode', CHARACTER_NAME_MODE)
    # 4 cơ chế hiệu ứng dựng cảnh (độc lập) — thứ tự ưu tiên: episode → project settings
    # → global env default. Giá trị '': coi như chưa đặt.
    fx_defaults = {
        'fx_flip':    '1' if SMART_SHOT_ALTERNATE_FLIP else '0',
        'fx_zoom':    '1' if SMART_SHOT_ZOOM_PERCENT > 100 else '0',
        'fx_speed':   '1' if SMART_SHOT_SPEED_MAX > 1.0 else '0',
        'fx_reverse': '1' if SMART_SHOT_REVERSE else '0',
    }
    for key in fx_defaults:
        val = options.get(key)
        if val is None or val == '':
            val = settings.get(key)
        if val is None or val == '':
            val = fx_defaults[key]
        options[key] = str(val)
    # free_order: mạch kể tự do đảo cảnh — thừa kế như các key trên, default '0'
    if not options.get('free_order'):
        options['free_order'] = settings.get('free_order') or ('1' if FREE_ORDER_DEFAULT else '0')
    return options


def _episode_updater(project_id, episode_id, task):
    """Tạo callback on_update đồng bộ tiến độ task -> episode trong database.
    Dùng chung cho process_project / retry_episode / manual-submit."""
    task.project_id = project_id
    task.episode_id = episode_id

    def on_update():
        updates = {
            'status':   task.status,
            'progress': task.progress,
            'message':  task.message,
            'error':    task.error,
        }
        if task.result_text:
            updates['manual_result'] = task.result_text
        # Đồng bộ TIẾN TRÌNH kịch bản: segments + ước lượng thời lượng theo từng giai đoạn
        # (AI trả về → est_sec; TTS xong → tts_sec thật; cắt shot xong → shot_count từng cảnh)
        # để modal luôn hiển thị được kịch bản NGAY khi AI đưa ra, kể cả đang chạy.
        if task.segments:
            updates['segments'] = [_segment_dict(s) if hasattr(s, 'start_time') else s
                                   for s in task.segments]
        if task.est_sec is not None:
            updates['est_sec'] = task.est_sec
        if task.tts_sec is not None:
            updates['tts_sec'] = task.tts_sec
        if task.target_sec is not None:
            updates['target_sec'] = task.target_sec
        if task.result and 'video_url' in task.result:
            updates['result_url'] = task.result['video_url']
            updates['srt_url']    = task.result.get('srt_url')
        database.update_episode(project_id, episode_id, updates)
        try:
            database.save_task(task.to_dict())
        except Exception:
            pass

    return on_update


def _manual_compressed_path(video_path: str) -> str:
    """Đường dẫn nén chuẩn DUY NHẤT dùng chung cho cả mode API và thủ công.
    Tên file cố định theo tên gốc episode (không timestamp) → mọi mode cùng tra cứu
    1 file nén đầu ra: có sẵn thì tái dùng, chưa có mới nén."""
    base2 = os.path.splitext(os.path.basename(video_path))[0]
    base2 = re.sub(r'^\d+_', '', base2)  # bỏ prefix timestamp upload
    return os.path.join(MANUAL_DIR, f'{base2}_manual{MANUAL_COMPRESS_TAG}.mp4')


def _ensure_studio_ready_path(video_path: str) -> str:
    """Bảo đảm file ≤ AI_STUDIO_UPLOAD_MAX_MB cho upload AI Studio NGAY TRƯỚC khi mở studio.
    Nếu file đã đủ nhỏ → dùng thẳng. Nếu lớn hơn ngưỡng → nén thêm bản upload ngay tại đây
    (xong mới mở studio, không nén trong lúc thao tác studio). Cache theo video gốc."""
    max_mb = float(AI_STUDIO_UPLOAD_MAX_MB or 38)
    if os.path.exists(video_path) and os.path.getsize(video_path) <= max_mb * 1024 * 1024:
        return video_path
    from backend.services.ai_studio_bridge import _upload_cache_path
    cache = _upload_cache_path(video_path)
    if os.path.exists(cache) and 0 < os.path.getsize(cache) <= max_mb * 1024 * 1024:
        return cache
    tmp = os.path.splitext(cache)[0] + '.tmp.mp4'
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    make_studio_upload_copy(video_path, max_mb, tmp)
    os.replace(tmp, cache)
    return cache


def _ensure_manual_compressed(t):
    """Nén file _sm (nếu chưa có) + bản ≤ ngưỡng upload AI Studio, set t.compressed_path.
    Gọi trong THREAD (không chặn HTTP request) — nén xong mới mở studio."""
    compressed = _manual_compressed_path(t.video_path)
    if not (os.path.exists(compressed) and os.path.getsize(compressed) > 10000):
        # Nén 1 pass duy nhất đã đủ nhỏ cho upload AI Studio (480p12fps + audio 64k:
        # tập 24 phút ~26MB < ngưỡng 38MB) → _ensure_studio_ready_path dùng thẳng,
        # khỏi pass 2 (tiết kiệm ~35s). Giữ fallback trong studio_ready cho file lạ.
        compress_video_for_upload(t.video_path, compressed, height=480, keep_audio=True, fps=12, light=True, cq='43', audio_bitrate='64k')
    # Đảm bảo file ≤ ngưỡng upload AI Studio NGAY TRƯỚC khi mở studio: nếu còn lớn hơn
    # thì nén thêm bản upload ở đây (xong mới mở studio, không nén trong lúc thao tác).
    t.compressed_path = _ensure_studio_ready_path(compressed)


def _get_task_series_description(t):
    """Lấy mô tả series (người dùng nhập ở cấp dự án) cho task — nhúng vào prompt mọi tập."""
    pid = getattr(t, 'project_id', None)
    if not pid:
        return ''
    try:
        p = database.get_project(pid)
        return (p or {}).get('settings', {}).get('series_description', '') or ''
    except Exception:
        return ''


def _setup_manual_task(t):
    """Nén video (nếu chưa có file nén thủ công) + dựng prompt cho task manual.

    Không chạy pipeline — người dùng tự gửi prompt lên AI Studio, dán kịch bản
    về rồi submit sau. Trả về dict {task_id, prompt, compressed_url, ...}."""
    _ensure_manual_compressed(t)
    target_words, num_segments, target_sec = _compute_targets(t.options)
    prev_dur = 0.0
    try:
        prev_dur = get_video_duration(t.video_path)
    except Exception:
        pass
    t.prompt = build_scene_prompt(t.options.get('style', 'narrative'), num_segments, target_words, target_sec, video_duration=prev_dur, characters=t.options.get('characters') or CHARACTER_REGISTRY, name_mode=t.options.get('character_name_mode', CHARACTER_NAME_MODE), series_description=_get_task_series_description(t), free_order=bool(t.options.get('free_order')))
    t.status = 'awaiting'
    return {'task_id': t.id, 'prompt': t.prompt, 'compressed_url': t.to_dict()['compressed_url'],
            'num_segments': num_segments, 'target_words': target_words}


def _prepare_manual_prompt(t):
    """Chỉ dựng prompt NHANH (không nén) cho task manual — dùng cho manual-run để
    trả response ngay, UI chuyển tranh tiến trình; nén do thread _run_ai_studio_auto lo."""
    target_words, num_segments, target_sec = _compute_targets(t.options)
    prev_dur = 0.0
    try:
        prev_dur = get_video_duration(t.video_path)
    except Exception:
        pass
    t.prompt = build_scene_prompt(t.options.get('style', 'narrative'), num_segments, target_words, target_sec, video_duration=prev_dur, characters=t.options.get('characters') or CHARACTER_REGISTRY, name_mode=t.options.get('character_name_mode', CHARACTER_NAME_MODE), series_description=_get_task_series_description(t), free_order=bool(t.options.get('free_order')))
    return {'task_id': t.id, 'prompt': t.prompt, 'compressed_url': None,
            'num_segments': num_segments, 'target_words': target_words}


def _auto_extract_episode_characters(task, segments):
    """Tự trích nhân vật của tập vừa chạy XONG → ghi bảng episode_characters.

    Dữ liệu này nuôi union registry `_auto_character_registry` cho các tập SAU, nên
    danh sách nhân vật của series tự đầy đủ mà không cần bấm nút gợi ý. Kịch bản
    không đổi (so narration_hash) thì tái dùng cache cũ, không gọi AI. Lỗi chỉ log — 
    không làm hỏng kết quả pipeline."""
    pid = getattr(task, 'project_id', None)
    eid = getattr(task, 'episode_id', None)
    if not pid or not eid:
        return
    nars = [((getattr(s, 'narration', None) or '').strip()) for s in (segments or [])]
    nars = [n for n in nars if n]
    if not nars:
        return
    script_text = '\n'.join(nars)
    narration_hash = hashlib.sha1(script_text.encode('utf-8')).hexdigest()
    if database.get_episode_characters_hash(pid, eid) == narration_hash:
        return
    try:
        name_mode = task.options.get('character_name_mode', CHARACTER_NAME_MODE)
        chars = extract_characters_from_script(script_text, name_mode)
        database.save_episode_characters(pid, eid, chars, narration_hash)
        logger.info(f"[AUTO-CHAR] Tập {eid}: tự trích {len(chars)} nhân vật -> episode_characters")
    except Exception as e:
        logger.warning(f"[AUTO-CHAR] Tập {eid}: tự trích thất bại (kịch bản vẫn hợp lệ) — {e}")


def _delete_episode_outputs(ep: dict) -> int:
    """Xóa toàn bộ file output cũ (final mp4 + srt) của tập trên đĩa trong output/final.

    Tên file do process_pipeline tạo: `{base}_summary_{ts}.mp4/.srt` với base lấy từ
    video_path (KHÔNG phải filename trong DB — file upload có thể thêm prefix số).
    Chỉ đụng file của tập này; trả về số file đã xóa."""
    if not ep:
        return 0
    src = ep.get('video_path') or ep.get('filename') or ''
    base = os.path.splitext(os.path.basename(src))[0]
    if not base:
        return 0
    deleted = 0
    try:
        if os.path.isdir(FINAL_DIR):
            for fn in os.listdir(FINAL_DIR):
                if fn.lower().startswith(base.lower() + '_summary_') and fn.lower().endswith(('.mp4', '.srt')):
                    try:
                        os.remove(os.path.join(FINAL_DIR, fn))
                        deleted += 1
                    except Exception:
                        pass
    except OSError:
        pass
    if deleted:
        logger.info(f"[SYNC] Đã xóa {deleted} file output của tập '{base}' trong output/final")
    return deleted


def _resolve_output_path(url: str):
    """Resolve URL /media/... hoặc /output/... về absolute path trong OUTPUT_DIR.
    Trả None nếu URL lạ hoặc path thoát ra ngoài OUTPUT_DIR (chống path traversal)."""
    if not url or not isinstance(url, str):
        return None
    rel = None
    if url.startswith('/media/'):
        rel = url[len('/media/'):]
    elif url.startswith('/output/'):
        rel = url[len('/output/'):]
    else:
        return None
    full = os.path.normpath(os.path.join(OUTPUT_DIR, rel.replace('/', os.sep)))
    if not full.startswith(os.path.abspath(OUTPUT_DIR) + os.sep):
        return None
    return full


def _delete_episode_related_files(ep: dict) -> dict:
    """Xóa TOÀN BỘ file liên quan của 1 tập khi người dùng ấn xóa:
    - video đầu ra + SRT trong output/final (pattern base_summary_* + exact result_url/srt_url)
    - video nén manual output/manual/*_manual_sm.mp4 + bản cache upload studio (_studio_upload_*.mp4)
    - video gốc trong uploads/ (giữ guard: chỉ xóa trong UPLOAD_DIR)
    - thư mục work temp của task (temp/work/{task_id})
    File nén/cache được tính TRƯỚC khi xóa source (cache key theo stat source).
    Trả về dict số file đã xóa theo nhóm."""
    counts = {'output': 0, 'compressed': 0, 'source': 0, 'temp': 0}
    if not ep:
        return counts
    counts['output'] += _delete_episode_outputs(ep)
    # Exact result_url/srt_url — đề phòng file lệch pattern base_summary_*.
    for key in ('result_url', 'srt_url'):
        fp = _resolve_output_path(ep.get(key) or '')
        if fp and os.path.isfile(fp):
            try:
                os.remove(fp)
                counts['output'] += 1
            except OSError as e:
                logger.warning(f"[DEL] Không xóa được output {fp}: {e}")
    vp = ep.get('video_path') or ''
    if vp:
        # Video nén manual dùng chung theo tên gốc (tập khác cùng tên gốc sẽ nén lại khi chạy).
        try:
            mp = _manual_compressed_path(vp)
            if os.path.isfile(mp):
                try:
                    os.remove(mp)
                    counts['compressed'] += 1
                except OSError as e:
                    logger.warning(f"[DEL] Không xóa được file nén {mp}: {e}")
        except Exception:
            pass
        # Cache upload studio (+ bản .tmp dở dang). Cần source còn tồn tại để tính key.
        try:
            from backend.services.ai_studio_bridge import _upload_cache_path
            cp = _upload_cache_path(vp)
            for cand in (cp, os.path.splitext(cp)[0] + '.tmp.mp4'):
                if cand and os.path.isfile(cand):
                    try:
                        os.remove(cand)
                        counts['compressed'] += 1
                    except OSError as e:
                        logger.warning(f"[DEL] Không xóa được cache studio {cand}: {e}")
        except Exception:
            pass
        # Video gốc — chỉ xóa trong UPLOAD_DIR.
        if os.path.isfile(vp):
            try:
                norm_vp = os.path.normcase(os.path.abspath(vp))
                norm_up = os.path.normcase(os.path.abspath(UPLOAD_DIR))
                if norm_vp.startswith(norm_up + os.sep):
                    os.remove(vp)
                    counts['source'] += 1
            except OSError as e:
                logger.warning(f"[DEL] Không xóa được video gốc {vp}: {e}")
    task_id = ep.get('task_id')
    if task_id:
        wd = os.path.join(TASK_WORK_ROOT, str(task_id))
        if os.path.isdir(wd):
            try:
                shutil.rmtree(wd, ignore_errors=True)
                counts['temp'] += 1
            except Exception as e:
                logger.warning(f"[DEL] Không xóa được thư mục work {wd}: {e}")
    if sum(counts.values()):
        logger.info(f"[DEL] Xóa file tập '{ep.get('filename') or ep.get('id')}': {counts}")
    return counts
