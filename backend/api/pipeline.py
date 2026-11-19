"""Pipeline xử lý video (tách ra từ backend/main.py).

Gồm `_process_pipeline` (thân pipeline), `process_pipeline` (wrapper hỗ trợ hủy ngắt cứng)
và `_run_ai_studio_auto` (worker chạy AI Studio tự động rồi đưa qua pipeline)."""
import os, shutil, threading
from datetime import datetime

from backend.core.config import *
from backend.services.video_service import (
    get_real_video_duration,
    get_video_duration,
    compress_video_for_upload,
    render_smart_shot,
    cut_merge_all_segments,
    concat_videos,
    create_srt,
    ffmpeg_cancel_context,
)
from backend.services.gemini_service import summarize_video, parse_result_text
from backend.services.tts_service import generate_all_tts
from backend.services.ai_studio_bridge import run_ai_studio_auto
from backend.utils.srt_parser import parse_segments, calculate_speed_adjustment, resolve_overlaps

from backend.api.deps import (
    logger,
    _compute_targets,
    _manual_compressed_path,
    _auto_extract_episode_characters,
    _ensure_manual_compressed,
    _get_task_series_description,
)


def _process_pipeline(task):
    def update(msg, pct):
        task.message = msg
        if pct is not None:
            task.progress = max(getattr(task, 'progress', 0), int(pct))
        if task.on_update:
            try: task.on_update()
            except Exception: pass


    def check_cancel():
        """Ném lỗi nếu task đã bị hủy/xóa — dừng pipeline ngay lập tức."""
        if task._cancelled:
            raise Exception('__CANCELLED__')

    update('Đọc thông tin video...', 5)
    check_cancel()
    v_dur = get_real_video_duration(task.video_path)
    base = os.path.splitext(os.path.basename(task.video_path))[0]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    target_words, num_segments, target_sec = _compute_targets(task.options, v_dur)
    task.target_sec = target_sec  # Dự kiến độ dài đầu ra (đủ dữ liệu: biết ngay khi chạy)
    style = task.options.get('style', 'narrative')
    # Thư mục làm việc RÊNG cho từng task: tránh ghi đè/xoá lẫn file trung gian
    # (seg/tts/merged/concat_list) khi nhiều tập chạy song song.
    task_work_dir = os.path.join(TASK_WORK_ROOT, task.id)
    os.makedirs(task_work_dir, exist_ok=True)
    task._tmp_paths = [task_work_dir]

    # Quyết định nguồn kịch bản: thủ công (có sẵn result_text) hay tự động gọi Gemini
    if task.options.get('mode') == 'manual' and task.result_text:
        raw = parse_result_text(task.result_text, characters=task.options.get('characters'), free_order=bool(task.options.get('free_order')))
        if not raw:
            raise Exception('Không parse được phân cảnh từ văn bản bạn nhập. Đảm bảo mỗi dòng đúng định dạng: MM:SS<TAB>nội dung')
        segments = parse_segments(raw)
    else:
        # Dùng CHUNG 1 file nén chuẩn (như mode thủ công) — tra cứu cùng đường dẫn,
        # có sẵn thì tái dùng, chưa có mới nén.
        compressed = _manual_compressed_path(task.video_path)
        if os.path.exists(compressed) and os.path.getsize(compressed) > 10000:
            update('Đã có video nén sẵn, bỏ qua bước nén...', 8)
        else:
            update('Nén video để gửi nhanh lên Gemini...', 6)
            check_cancel()
            compress_video_for_upload(task.video_path, compressed, height=480, fps=12, keep_audio=True, light=True)
        task.compressed_path = compressed
        if os.path.abspath(task.compressed_path).startswith(os.path.abspath(TEMP_DIR)):
            task._tmp_paths.append(task.compressed_path)

        check_cancel()
        # Bước MẠNG phải tối đa MAX_NETWORK_EPISODES tập: siết bằng semaphore.
        # Khóa phần cứng (LOCAL_HARDWARE_LOCK) KHÔNG giữ ở đây — Gemini không dùng CPU cục bộ,
        # nên các tập khác vẫn nén/cắt được trong lúc chờ Gemini.
        with NETWORK_EPISODE_LOCK:
            raw = summarize_video(compressed, style=style, model_name=task.options.get('model', ''), num_segments=num_segments, target_words=target_words, target_sec=target_sec, video_duration=v_dur, progress_callback=update, characters=task.options.get('characters'), name_mode=task.options.get('character_name_mode', CHARACTER_NAME_MODE), series_description=_get_task_series_description(task), free_order=bool(task.options.get('free_order')))
            check_cancel()
            segments = parse_segments(raw)
    task.segments = segments
    task.est_sec = int(sum(len((s.narration or '').split()) for s in segments) / max(WORDS_PER_MINUTE / 60, 0.1))  # ước đọc kịch bản AI
    # Đẩy ngay để UI hiển thị kịch bản + ước lượng thời lượng video đầu ra MÀ KHÔNG đợi TTS
    update('Đã có kịch bản AI. Bắt đầu tạo giọng đọc...', 39)


    check_cancel()
    # VoiceStudio local (localhost) KHÔNG chiếm slot mạng — nó tự siết bằng
    # VOICESTUDIO_GLOBAL_SEM riêng. Chỉ giọng cloud (CapCut) mới cần NETWORK_EPISODE_LOCK.
    _vtype = ((VOICES.get(task.options.get('voice_id') or '') or {}).get('type')
              or (VOICES.get(DEFAULT_VOICE) or {}).get('type', 'capcut'))
    _tts_kwargs = dict(voice_key=task.options.get('voice_id'), progress_callback=update, work_dir=task_work_dir, is_cancelled=lambda: task._cancelled, ref_audio=task.options.get('tts_ref_audio'), ref_text=task.options.get('tts_ref_text'), speed=task.options.get('tts_speed') or None)
    if _vtype == 'voicestudio':
        segments = generate_all_tts(segments, **_tts_kwargs)
    else:
        with NETWORK_EPISODE_LOCK:
            segments = generate_all_tts(segments, **_tts_kwargs)
    check_cancel()
    task.tts_sec = round(sum(s.tts_duration for s in segments if getattr(s, 'tts_duration', 0) > 0), 1)  # thời lượng LỜI BÌNH thật (chuẩn sau TTS)
    task.segments = segments
    update('Đã tạo giọng đọc xong. Tính toán timing & cắt ghép...', 61)
    segments = calculate_speed_adjustment(segments, v_dur)
    segments = resolve_overlaps(segments, v_dur)

    check_cancel()
    # Chế độ dựng: 'smart_shot' (mặc định) → phát hiện shot + edit plan + render theo shot;
    # 'legacy' → giữ nguyên chia đôi/đảo cảnh cũ như trước.
    if task.options.get('edit_mode') == 'smart_shot':
        merged = render_smart_shot(task.video_path, segments, edit_mode='smart_shot',
                                   progress_callback=update, work_dir=task_work_dir, opts=task.options,
                                   is_cancelled=lambda: task._cancelled,
                                   register=task.register_proc, unregister=task.unregister_proc)
    else:
        merged = cut_merge_all_segments(task.video_path, segments, progress_callback=update, work_dir=task_work_dir,
                                        is_cancelled=lambda: task._cancelled,
                                        register=task.register_proc, unregister=task.unregister_proc)
    task.segments = segments
    task._tmp_paths.extend([m for m in (merged or []) if m and os.path.exists(m)])
    update('Đã dựng xong các phân cảnh (số shot từng cảnh đã cập nhật). Ghép audio hoàn chỉnh...', 86)

    check_cancel()
    update('Nối video hoàn chỉnh...', 88)
    final_raw = os.path.join(FINAL_DIR, f'{base}_summary_{ts}.mp4')
    # Các segment đều qua _merge_one với cùng tham số (1080p30 CFR + AAC) → thử nối
    # copy trước (nhanh, giữ nguyên chất lượng); lệch/thất bại tự về re-encode.
    concat_videos(merged, final_raw, work_dir=task_work_dir, try_copy_first=True)
    check_cancel()  # hủy đúng lúc đang concat → video dang dở sẽ bị dọn trong wrapper

    srt_out = os.path.join(FINAL_DIR, f'{base}_summary_{ts}.srt')
    create_srt(segments, srt_out)
    task._tmp_paths.extend([final_raw, srt_out])

    # Tự động dọn dẹp các phân đoạn trung gian để tiết kiệm dung lượng ổ đĩa SSD
    for m in (merged or []):
        if m and os.path.exists(m):
            try: os.remove(m)
            except Exception: pass
    for seg in (segments or []):
        if hasattr(seg, 'video_segment_path') and seg.video_segment_path and os.path.exists(seg.video_segment_path):
            try: os.remove(seg.video_segment_path)
            except Exception: pass
        if hasattr(seg, 'tts_audio_path') and seg.tts_audio_path and os.path.exists(seg.tts_audio_path):
            try: os.remove(seg.tts_audio_path)
            except Exception: pass
    if task.compressed_path and os.path.abspath(task.compressed_path).startswith(os.path.abspath(TEMP_DIR)):
        if os.path.exists(task.compressed_path):
            try: os.remove(task.compressed_path)
            except Exception: pass
    try: shutil.rmtree(task_work_dir, ignore_errors=True)
    except Exception: pass

    update('Đã dựng xong video! Đang hoàn thiện...', 95)
    output_sec = 0.0
    try:
        output_sec = get_video_duration(final_raw)
    except Exception:
        pass
    task.output_sec = output_sec
    task.result = {
        'video_url': f'/media/{os.path.relpath(final_raw, OUTPUT_DIR).replace(chr(92), "/")}',
        'srt_url': f'/output/{os.path.relpath(srt_out, OUTPUT_DIR).replace(chr(92), "/")}',
        'duration_original': v_dur,
        'duration_output': output_sec,
        'segments_count': len(segments)
    }

    # Tự trích nhân vật của tập vừa xong (bảng episode_characters -> registry tập sau).
    # Gọi Gemini nên mất thêm 15-60s: báo tiến trình thật để UI không đứng ở "Hoàn tất!".
    update('Video xong! Đang tự trích nhân vật cho các tập sau...', 98)
    _auto_extract_episode_characters(task, segments)
    update('Hoàn tất!', 99)

def _cleanup_cancelled_paths(task):
    """Dọn file/thư mục trung gian + video/srt dang dở của task bị hủy giữa chừng."""
    for p in list(getattr(task, '_tmp_paths', None) or []):
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.isfile(p):
                os.remove(p)
        except Exception:
            pass
    task._tmp_paths = []

def process_pipeline(task):
    """Pipeline có hỗ trợ hủy NGẮT CỨNG: đặt ngữ cảnh hủy để mọi ffmpeg subprocess tự
    đăng ký vào task → force_cancel kill ngay khi hủy; các bước dài (TTS, detect_shots)
    tự thoát; file trung gian + output dang dở được dọn sạch."""
    try:
        with ffmpeg_cancel_context(lambda: task._cancelled, task.register_proc, task.unregister_proc):
            _process_pipeline(task)
    except Exception as e:
        if task._cancelled or '__CANCELLED__' in str(e):
            _cleanup_cancelled_paths(task)
        raise


def _run_ai_studio_auto(t):
    """Worker: tự thao tác Google AI Studio (Chrome profile automation + CDP) lấy kịch bản,
    rồi chạy pipeline. Dùng chung cho /api/manual/auto-run và nút Run 1-chạm của tập manual.
    Hỗ trợ hủy giữa chừng: cờ _cancelled được kiểm tra trong từng bước thao tác."""
    def step(msg):
        t.message = msg
        if t.on_update:
            try: t.on_update()
            except Exception: pass
    try:
        # Nén xong file + bản ≤ ngưỡng upload NGAY TRONG THREAD TRƯỚC khi mở studio —
        # không chặn HTTP request, và đảm bảo studio mở khi file nén đã sẵn sàng.
        with ffmpeg_cancel_context(lambda: t._cancelled, t.register_proc, t.unregister_proc):
            _ensure_manual_compressed(t)
        step(f"Nén xong ({os.path.getsize(t.compressed_path)//(1024*1024)}MB), bắt đầu thao tác trên Google AI Studio...")
        result = run_ai_studio_auto(
            prompt=t.prompt,
            video_path=t.compressed_path,
            output_write=step,
            is_cancelled=lambda: t._cancelled,
            wait_user_submit=True,
            model=t.options.get('model', ''),
        )
        if t._cancelled:
            raise RuntimeError('__CANCELLED__')
        t.result_text = result
        if t.on_update:
            try: t.on_update()
            except Exception: pass
        step('Đã nhận kịch bản từ AI Studio. Đang bắt đầu tạo video...')
        process_pipeline(t)
        t.status = 'completed'
        t.progress = 100
        t.message = 'Hoàn tất video tóm tắt!'
        t.completed_at = datetime.now().isoformat()
        if t.on_update:
            try: t.on_update()
            except Exception: pass
    except Exception as e:
        if t._cancelled or '__CANCELLED__' in str(e):
            t.status = 'cancelled'
            t.error = None
            t.message = 'Đã hủy bởi người dùng'
        else:
            t.status = 'failed'
            t.error = str(e)
            t.message = f'Lỗi tự động AI Studio: {e}'
        if t.on_update:
            try: t.on_update()
            except Exception: pass
