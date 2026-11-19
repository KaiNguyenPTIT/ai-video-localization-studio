import os
import json
import logging
from datetime import datetime
from .config import OUTPUT_DIR, DATA_DIR
from .db_engine import get_db_cursor, init_db
from backend.utils.srt_parser import time_to_seconds

logger = logging.getLogger(__name__)

OLD_JSON_FILE = os.path.join(DATA_DIR, 'projects.json')

def _resolve_url_to_path(url: str) -> str:
    """Chuyển đổi URL tĩnh dạng /media/... hoặc /output/... thành đường dẫn tuyệt đối trên đĩa."""
    if not url or not isinstance(url, str):
        return ''
    if url.startswith('/media/'):
        rel = url.split('/media/', 1)[-1].replace('/', os.sep)
        return os.path.abspath(os.path.join(OUTPUT_DIR, rel))
    if url.startswith('/output/'):
        rel = url.split('/output/', 1)[-1].replace('/', os.sep)
        return os.path.abspath(os.path.join(OUTPUT_DIR, rel))
    return ''

def _parse_time_val(val) -> tuple[str, float]:
    """Parse linh hoạt timestamp (chuỗi '00:08', '00:00:08,123' hoặc float) trả về (str, float_sec)."""
    if val is None:
        return ('00:00:00', 0.0)
    if isinstance(val, (int, float)):
        return (str(val), float(val))
    val_str = str(val).strip()
    try:
        sec = time_to_seconds(val_str)
        return (val_str, sec)
    except Exception:
        try:
            sec = float(val_str)
            return (val_str, sec)
        except Exception:
            return (val_str, 0.0)

def check_and_migrate_from_json():
    """Tự động kiểm tra và di chuyển dữ liệu từ output/projects.json sang SQLite MMDBMS."""
    init_db()

    if not os.path.exists(OLD_JSON_FILE):
        return False

    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) FROM projects;")
        count = cur.fetchone()[0]
        if count > 0:
            # Đã có dữ liệu trong SQLite, không di chuyển đè lên
            return False

    logger.info("Phát hiện dữ liệu cũ trong projects.json, đang tiến hành di chuyển sang SQLite...")
    try:
        with open(OLD_JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Không thể đọc {OLD_JSON_FILE} để di chuyển: {e}")
        return False

    projects_data = data.get("projects", {})
    if not projects_data:
        return False

    migrated_projects = 0
    migrated_episodes = 0
    migrated_segments = 0
    migrated_assets = 0

    with get_db_cursor(commit=True) as cur:
        for pid, p in projects_data.items():
            name = p.get('name', 'Chưa đặt tên')
            created_at = p.get('created_at', datetime.now().isoformat())
            updated_at = p.get('updated_at')
            settings = p.get('settings', {})
            settings_json = json.dumps(settings, ensure_ascii=False)

            cur.execute("""
                INSERT OR REPLACE INTO projects (id, name, created_at, updated_at, settings_json)
                VALUES (?, ?, ?, ?, ?);
            """, (pid, name, created_at, updated_at, settings_json))
            migrated_projects += 1

            # Check merge video trong project settings nếu có
            last_merge = settings.get('last_merge') if isinstance(settings, dict) else None
            if last_merge and isinstance(last_merge, dict):
                m_vid_url = last_merge.get('video_url', '')
                m_srt_url = last_merge.get('srt_url', '')
                m_vid_path = _resolve_url_to_path(m_vid_url)
                m_srt_path = _resolve_url_to_path(m_srt_url)

                if m_vid_path and os.path.isfile(m_vid_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (project_id, asset_type, file_path, url_path, file_size, created_at)
                        VALUES (?, 'merged_video', ?, ?, ?, ?);
                    """, (pid, m_vid_path, m_vid_url, os.path.getsize(m_vid_path), created_at))
                    migrated_assets += 1

                if m_srt_path and os.path.isfile(m_srt_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (project_id, asset_type, file_path, url_path, file_size, created_at)
                        VALUES (?, 'merged_srt', ?, ?, ?, ?);
                    """, (pid, m_srt_path, m_srt_url, os.path.getsize(m_srt_path), created_at))
                    migrated_assets += 1

            # Xử lý episodes
            for ep in p.get('episodes', []):
                eid = ep.get('id')
                if not eid:
                    continue

                filename = ep.get('filename', '')
                video_path = ep.get('video_path', '')
                options_json = json.dumps(ep.get('options', {}), ensure_ascii=False)
                status = ep.get('status', 'pending')
                progress = ep.get('progress', 0)
                message = ep.get('message', '')
                result_url = ep.get('result_url')
                srt_url = ep.get('srt_url')
                error = ep.get('error')
                ep_created_at = ep.get('created_at', datetime.now().isoformat())
                completed_at = ep.get('completed_at')
                manual_prompt = ep.get('manual_prompt')
                manual_result = ep.get('manual_result')
                manual_compressed_url = ep.get('manual_compressed_url')
                num_segments = ep.get('num_segments', 0)
                target_words = ep.get('target_words', 0)
                task_id = ep.get('task_id')

                cur.execute("""
                    INSERT OR REPLACE INTO episodes (
                        id, project_id, filename, video_path, options_json,
                        status, progress, message, result_url, srt_url,
                        error, created_at, completed_at, manual_prompt, manual_result,
                        manual_compressed_url, num_segments, target_words, task_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    eid, pid, filename, video_path, options_json,
                    status, progress, message, result_url, srt_url,
                    error, ep_created_at, completed_at, manual_prompt, manual_result,
                    manual_compressed_url, num_segments, target_words, task_id
                ))
                migrated_episodes += 1

                # Đăng ký media assets liên quan đến episode
                if video_path and os.path.isfile(video_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (episode_id, project_id, asset_type, file_path, file_size, created_at)
                        VALUES (?, ?, 'source_video', ?, ?, ?);
                    """, (eid, pid, video_path, os.path.getsize(video_path), ep_created_at))
                    migrated_assets += 1

                final_vid_path = _resolve_url_to_path(result_url)
                if final_vid_path and os.path.isfile(final_vid_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                        VALUES (?, ?, 'final_video', ?, ?, ?, ?);
                    """, (eid, pid, final_vid_path, result_url, os.path.getsize(final_vid_path), completed_at or ep_created_at))
                    migrated_assets += 1

                final_srt_path = _resolve_url_to_path(srt_url)
                if final_srt_path and os.path.isfile(final_srt_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                        VALUES (?, ?, 'final_srt', ?, ?, ?, ?);
                    """, (eid, pid, final_srt_path, srt_url, os.path.getsize(final_srt_path), completed_at or ep_created_at))
                    migrated_assets += 1

                comp_path = _resolve_url_to_path(manual_compressed_url)
                if comp_path and os.path.isfile(comp_path):
                    cur.execute("""
                        INSERT OR IGNORE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                        VALUES (?, ?, 'manual_compressed', ?, ?, ?, ?);
                    """, (eid, pid, comp_path, manual_compressed_url, os.path.getsize(comp_path), ep_created_at))
                    migrated_assets += 1

                # Di chuyển segments
                segments = ep.get('segments') or []
                for idx, seg in enumerate(segments):
                    raw_st = seg.get('start_time') if isinstance(seg, dict) else getattr(seg, 'start_time', None)
                    raw_et = seg.get('end_time') if isinstance(seg, dict) else getattr(seg, 'end_time', None)
                    st_str, st_sec = _parse_time_val(raw_st)
                    et_str, et_sec = _parse_time_val(raw_et)
                    narration = (seg.get('narration', '') if isinstance(seg, dict) else getattr(seg, 'narration', '')) or ''

                    cur.execute("""
                        INSERT INTO segments (episode_id, index_num, start_time, end_time, start_seconds, end_seconds, narration)
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (eid, idx, st_str, et_str, st_sec, et_sec, narration))
                    migrated_segments += 1

                    # Thêm vào FTS index
                    if narration.strip():
                        time_range = f"{st_str} --> {et_str}"
                        cur.execute("""
                            INSERT INTO segments_fts (narration, episode_id, project_id, time_range)
                            VALUES (?, ?, ?, ?);
                        """, (narration, eid, pid, time_range))

    # Backup file cũ
    backup_file = OLD_JSON_FILE + '.bak'
    try:
        if not os.path.exists(backup_file):
            import shutil
            shutil.copy2(OLD_JSON_FILE, backup_file)
    except Exception as e:
        logger.warning(f"Không thể sao lưu file backup {backup_file}: {e}")

    logger.info(f"Hoàn thành di chuyển dữ liệu: {migrated_projects} dự án, {migrated_episodes} tập, {migrated_segments} phân cảnh, {migrated_assets} tài nguyên đa phương tiện.")
    return True
