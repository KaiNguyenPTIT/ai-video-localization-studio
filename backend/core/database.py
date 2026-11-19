import os
import json
import uuid
import logging
from datetime import datetime
from .config import OUTPUT_DIR, BASE_DIR
from .db_engine import get_db_cursor, init_db
from .db_migration import check_and_migrate_from_json, _resolve_url_to_path, _parse_time_val

logger = logging.getLogger(__name__)

# Khởi tạo DB và chạy di trú nếu cần khi import module
init_db()
check_and_migrate_from_json()

# ── Helper Mappers ─────────────────────────────────────────────

def _row_to_project(p_row, episodes=None, characters=None) -> dict:
    if not p_row:
        return None
    settings = {}
    try:
        if p_row['settings_json']:
            settings = json.loads(p_row['settings_json'])
    except Exception:
        settings = {}
    chars = characters if characters is not None else []
    if not chars:
        try:
            chars = json.loads(p_row['characters_json'] or '[]')
        except Exception:
            chars = []
    return {
        "id": p_row['id'],
        "name": p_row['name'],
        "created_at": p_row['created_at'],
        "updated_at": p_row['updated_at'],
        "settings": settings,
        "characters": chars,
        "episodes": episodes if episodes is not None else []
    }

def _row_to_episode(e_row, segments=None) -> dict:
    if not e_row:
        return None
    options = {}
    try:
        if e_row['options_json']:
            options = json.loads(e_row['options_json'])
    except Exception:
        options = {}

    status = e_row['status']
    res_url = e_row['result_url']
    srt_url = e_row['srt_url']
    msg = e_row['message']

    # Tự động đồng bộ: nếu tập báo completed nhưng file video không còn trên đĩa
    if status == 'completed' and res_url:
        p = _resolve_url_to_path(res_url)
        if not (p and os.path.isfile(p)):
            status = 'pending'
            res_url = None
            srt_url = None
            msg = 'Video thành phẩm đã bị xóa hoặc không tìm thấy trên ổ đĩa'

    return {
        "id": e_row['id'],
        "project_id": e_row['project_id'],
        "filename": e_row['filename'],
        "video_path": e_row['video_path'],
        "options": options,
        "status": status,
        "progress": e_row['progress'],
        "message": msg,
        "result_url": res_url,
        "srt_url": srt_url,
        "error": e_row['error'],
        "created_at": e_row['created_at'],
        "completed_at": e_row['completed_at'] if status == 'completed' else None,
        "manual_prompt": e_row['manual_prompt'],
        "manual_result": e_row['manual_result'],
        "manual_compressed_url": e_row['manual_compressed_url'],
        "num_segments": e_row['num_segments'],
        "target_words": e_row['target_words'],
        "target_sec": e_row['target_sec'],
        "est_sec": e_row['est_sec'],
        "tts_sec": e_row['tts_sec'],
        "task_id": e_row['task_id'],
        "characters_reviewed": e_row['characters_reviewed'] if 'characters_reviewed' in e_row.keys() else None,
        "segments": segments if segments is not None else []
    }

def _ensure_project_characters_column():
    """Thêm cột characters_json cho bảng projects nếu DB cũ chưa có."""
    with get_db_cursor(commit=False) as cur:
        cols = {r['name'] for r in cur.execute("PRAGMA table_info(projects)").fetchall()}
        if 'characters_json' not in cols:
            cur.execute("ALTER TABLE projects ADD COLUMN characters_json TEXT DEFAULT '[]'")

def sync_on_library_deleted(base_name: str, project_id: str = None) -> dict:
    """Khi người dùng xóa video/srt trong Thư viện, tự động đồng bộ lại bảng episodes và projects."""
    affected_episodes = []
    with get_db_cursor(commit=True) as cur:
        # Tìm các tập có result_url hoặc srt_url chứa base_name
        search_pattern = f"%{base_name}%"
        cur.execute("""
            SELECT id, project_id, filename, result_url, srt_url
            FROM episodes
            WHERE (result_url LIKE ? OR srt_url LIKE ?);
        """, (search_pattern, search_pattern))
        rows = cur.fetchall()

        for r in rows:
            eid = r['id']
            pid = r['project_id']
            cur.execute("""
                UPDATE episodes
                SET status = 'pending',
                    result_url = NULL,
                    srt_url = NULL,
                    completed_at = NULL,
                    progress = 0,
                    message = 'Video thành phẩm đã bị xóa khỏi Thư viện'
                WHERE id = ? AND project_id = ?;
            """, (eid, pid))
            cur.execute("DELETE FROM media_assets WHERE episode_id = ? AND asset_type IN ('final_video', 'final_srt');", (eid,))
            affected_episodes.append({'episode_id': eid, 'project_id': pid})

        # Xóa last_merge trong projects nếu là video ghép
        cur.execute("SELECT id, settings_json FROM projects WHERE settings_json LIKE ?;", (search_pattern,))
        p_rows = cur.fetchall()
        for pr in p_rows:
            try:
                s = json.loads(pr['settings_json'] or '{}')
                if 'last_merge' in s:
                    del s['last_merge']
                    cur.execute("UPDATE projects SET settings_json = ? WHERE id = ?;", (json.dumps(s, ensure_ascii=False), pr['id']))
            except Exception:
                pass

        # Dọn bản ghi merge (merged_video/merged_srt) của project bị xóa video ghép —
        # sync cũ chỉ dọn final_video/final_srt theo episode nên rows merge thành mồ côi.
        if project_id:
            cur.execute("""
                DELETE FROM media_assets
                WHERE project_id = ? AND asset_type IN ('merged_video', 'merged_srt')
                  AND file_path LIKE ?;
            """, (project_id, f"%{base_name}%"))

    if affected_episodes:
        logger.info(f"[SYNC] Đã đồng bộ {len(affected_episodes)} tập phim về trạng thái pending do video bị xóa khỏi Thư viện: {base_name}")

    return {'affected_episodes': len(affected_episodes)}


# ── Projects ──────────────────────────────────────────────────

def get_all_projects() -> list[dict]:
    """Lấy danh sách tất cả các dự án kèm các tập phim bên trong, sắp xếp dự án hoạt động gần nhất lên đầu."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM projects ORDER BY COALESCE(updated_at, created_at) DESC;")
        project_rows = cur.fetchall()
        if not project_rows:
            return []

        cur.execute("SELECT * FROM episodes ORDER BY created_at ASC;")
        ep_rows = cur.fetchall()

        # Nhóm episodes theo project_id
        ep_map = {}
        for er in ep_rows:
            pid = er['project_id']
            ep_map.setdefault(pid, []).append(_row_to_episode(er, segments=[]))

        projects = []
        for pr in project_rows:
            pid = pr['id']
            eps = ep_map.get(pid, [])
            projects.append(_row_to_project(pr, episodes=eps))

        return projects

def get_project(project_id: str) -> dict | None:
    """Lấy chi tiết 1 dự án và danh sách tập phim kèm phân cảnh."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM projects WHERE id = ?;", (project_id,))
        pr = cur.fetchone()
        if not pr:
            return None
        characters = json.loads(pr['characters_json'] or '[]')

        cur.execute("SELECT * FROM episodes WHERE project_id = ? ORDER BY created_at ASC;", (project_id,))
        ep_rows = cur.fetchall()

        # Lấy segments cho các tập của project này
        cur.execute("""
            SELECT s.* FROM segments s
            JOIN episodes e ON s.episode_id = e.id
            WHERE e.project_id = ?
            ORDER BY s.episode_id, s.index_num ASC;
        """, (project_id,))
        seg_rows = cur.fetchall()
        seg_map = {}
        for sr in seg_rows:
            eid = sr['episode_id']
            seg_map.setdefault(eid, []).append({
                "index": sr['index_num'],
                "start_time": sr['start_time'],
                "end_time": sr['end_time'],
                "narration": sr['narration'],
                "tts_duration": sr['tts_duration'] or 0,
                "shot_count": sr['shot_count'] or 0
            })

        episodes = []
        for er in ep_rows:
            eid = er['id']
            episodes.append(_row_to_episode(er, segments=seg_map.get(eid, [])))

        return _row_to_project(pr, episodes=episodes, characters=characters)

def create_project(name: str, settings: dict = None, characters: list = None) -> dict:
    pid = str(uuid.uuid4())[:8]
    now_iso = datetime.now().isoformat()
    settings = settings or {}
    settings_json = json.dumps(settings, ensure_ascii=False)
    characters = characters or []
    characters_json = json.dumps(characters, ensure_ascii=False)

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO projects (id, name, created_at, settings_json, characters_json)
            VALUES (?, ?, ?, ?, ?);
        """, (pid, name, now_iso, settings_json, characters_json))

    return {
        "id": pid,
        "name": name,
        "created_at": now_iso,
        "settings": settings,
        "characters": characters,
        "episodes": []
    }

def update_project(project_id: str, name: str = None, settings: dict = None, characters: list = None) -> dict | None:
    """Cập nhật tên hoặc settings của project."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM projects WHERE id = ?;", (project_id,))
        pr = cur.fetchone()
        if not pr:
            return None

        now_iso = datetime.now().isoformat()
        new_name = name if name is not None else pr['name']
        if settings is not None:
            new_settings_json = json.dumps(settings, ensure_ascii=False)
        else:
            new_settings_json = pr['settings_json']
        if characters is not None:
            new_characters_json = json.dumps(characters, ensure_ascii=False)
        else:
            new_characters_json = pr['characters_json']

        cur.execute("""
            UPDATE projects
            SET name = ?, settings_json = ?, characters_json = ?, updated_at = ?
            WHERE id = ?;
        """, (new_name, new_settings_json, new_characters_json, now_iso, project_id))

        # Đăng ký tài nguyên merge nếu có trong settings mới
        if settings and isinstance(settings, dict):
            last_merge = settings.get('last_merge')
            if last_merge and isinstance(last_merge, dict):
                m_vid_url = last_merge.get('video_url', '')
                m_srt_url = last_merge.get('srt_url', '')
                m_vid_path = _resolve_url_to_path(m_vid_url)
                m_srt_path = _resolve_url_to_path(m_srt_url)
                if m_vid_path and os.path.isfile(m_vid_path):
                    register_media_asset(m_vid_path, 'merged_video', project_id=project_id, url_path=m_vid_url)
                if m_srt_path and os.path.isfile(m_srt_path):
                    register_media_asset(m_srt_path, 'merged_srt', project_id=project_id, url_path=m_srt_url)

    return get_project(project_id)

def delete_project(project_id: str) -> bool:
    """Xóa dự án khỏi cơ sở dữ liệu (tự động xóa episodes, segments và media_assets qua CASCADE).
    segments_fts là bảng FTS không có FK nên phải xóa tay trước khi xóa episodes."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM projects WHERE id = ?;", (project_id,))
        if not cur.fetchone():
            return False
        cur.execute("DELETE FROM segments_fts WHERE episode_id IN (SELECT id FROM episodes WHERE project_id = ?);", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = ?;", (project_id,))
        return True

# ── Episode characters (cache nhân vật THEO TẬP) ─────────────────

def save_episode_characters(project_id: str, episode_id: str, characters: list, narration_hash: str = '') -> list:
    """Ghi đè toàn bộ nhân vật đã trích xuất của MỘT tập (cache). characters = [{name, aliases}]."""
    now_iso = datetime.now().isoformat()
    avec = []
    seen = set()
    for c in characters or []:
        name = ((c.get('name') or '').strip())
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        alias = [a for a in (c.get('aliases') or []) if a and a.strip() != name]
        avec.append({'name': name, 'aliases': alias})
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM episode_characters WHERE episode_id = ?;", (episode_id,))
        for c in avec:
            cur.execute("""
                INSERT INTO episode_characters (project_id, episode_id, name, aliases_json, narration_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (project_id, episode_id, c['name'],
                  json.dumps(c['aliases'], ensure_ascii=False), narration_hash, now_iso))
    return avec

def get_episode_characters(project_id: str, episode_id: str) -> list:
    """Trả [{name, aliases}] đã cache của 1 tập (rỗng nếu chưa có)."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT name, aliases_json FROM episode_characters
            WHERE episode_id = ? AND project_id = ?
            ORDER BY id ASC;
        """, (episode_id, project_id))
        return [{'name': r['name'], 'aliases': json.loads(r['aliases_json'] or '[]')} for r in cur.fetchall()]

def get_episode_characters_hash(project_id: str, episode_id: str) -> str:
    """narration_hash của bản cache hiện tại ('' nếu chưa cache)."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT narration_hash FROM episode_characters
            WHERE episode_id = ? AND project_id = ?
            ORDER BY id ASC LIMIT 1;
        """, (episode_id, project_id))
        row = cur.fetchone()
        return row['narration_hash'] if row else ''

def _get_project_character_names(project_id: str) -> set:
    """Tập tên nhân vật (lowercase) của BẢNG CHUNG dự án (projects.characters_json)."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT characters_json FROM projects WHERE id = ?;", (project_id,))
        row = cur.fetchone()
        if not row:
            return set()
        try:
            chars = json.loads(row['characters_json'] or '[]')
        except Exception:
            return set()
        return {(c.get('name') or '').strip().lower()
                for c in (chars or []) if isinstance(c, dict) and (c.get('name') or '').strip()}


def get_episode_characters_reviewed_flag(project_id: str, episode_id: str):
    """Cờ reviewed THÔ của 1 tập: 1 = đã xét (tay), 0 = ép chưa xét, None = tự động."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT characters_reviewed FROM episodes WHERE id = ? AND project_id = ?;",
                    (episode_id, project_id))
        row = cur.fetchone()
        return row['characters_reviewed'] if row else None


def set_episode_characters_reviewed(project_id: str, episode_id: str, reviewed) -> bool:
    """Đặt cờ reviewed của 1 tập: True → 1, False → 0, None → NULL (về tự động)."""
    val = None if reviewed is None else (1 if reviewed else 0)
    with get_db_cursor(commit=True) as cur:
        cur.execute("UPDATE episodes SET characters_reviewed = ? WHERE id = ? AND project_id = ?;",
                    (val, episode_id, project_id))
        return cur.rowcount > 0


def is_episode_characters_reviewed(project_id: str, episode_id: str, project_chars=None) -> bool:
    """Tập đã xét (HIỆU DỤNG) hay chưa: cờ tay 1 → True; cờ 0 → False;
    cờ NULL (tự động) → True khi tập có cache nhân vật non-empty VÀ mọi tên
    đã nằm trong bảng chung (tập cũ duyệt trước khi có tính năng này)."""
    flag = get_episode_characters_reviewed_flag(project_id, episode_id)
    if flag == 1:
        return True
    if flag == 0:
        return False
    cached = get_episode_characters(project_id, episode_id)
    if not cached:
        return False
    if project_chars is None:
        common = _get_project_character_names(project_id)
    else:
        common = {(c.get('name') or '').strip().lower()
                  for c in (project_chars or []) if isinstance(c, dict) and (c.get('name') or '').strip()}
    if not common:
        return False
    return all((c.get('name') or '').strip().lower() in common for c in cached)


def get_reviewed_episode_ids(project_id: str, project_chars=None) -> set:
    """ID các tập đã xét (hiệu dụng) trong dự án — registry prompt sẽ LOẠI các tập này."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT id, characters_reviewed FROM episodes WHERE project_id = ?;", (project_id,))
        flags = {r['id']: r['characters_reviewed'] for r in cur.fetchall()}
    out = {eid for eid, f in flags.items() if f == 1}
    auto_ids = [eid for eid, f in flags.items() if f is None]
    if not auto_ids:
        return out
    if project_chars is None:
        common = _get_project_character_names(project_id)
    else:
        common = {(c.get('name') or '').strip().lower()
                  for c in (project_chars or []) if isinstance(c, dict) and (c.get('name') or '').strip()}
    if not common:
        return out
    with get_db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT episode_id AS eid, name FROM episode_characters
            WHERE project_id = ?;
        """, (project_id,))
        per = {}
        for r in cur.fetchall():
            per.setdefault(r['eid'], []).append((r['name'] or '').strip().lower())
    for eid in auto_ids:
        names = per.get(eid)
        if names and all(n in common for n in names):
            out.add(eid)
    return out


def get_project_episode_characters(project_id: str) -> list:
    """Trả danh sách nhân vật cache theo TỪNG TẬP của cả dự án (kèm filename, count lời bình)."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("""
            SELECT e.id AS eid, e.project_id AS pid, e.filename, e.created_at AS e_created,
                   ec.id, ec.name, ec.aliases_json, ec.narration_hash
            FROM episode_characters ec
            JOIN episodes e ON e.id = ec.episode_id
            WHERE e.project_id = ?
            ORDER BY e.created_at ASC, ec.id ASC;
        """, (project_id,))
        rows = cur.fetchall()
        cur.execute("""
            SELECT s.episode_id AS eid, COUNT(s.id) AS n
            FROM segments s
            JOIN episodes e ON e.id = s.episode_id
            WHERE e.project_id = ?
            GROUP BY s.episode_id;
        """, (project_id,))
        seg_counts = {r['eid']: r['n'] for r in cur.fetchall()}
    per = {}
    cur_hash = {}
    for r in rows:
        eid = r['eid']
        per.setdefault(eid, {'episode_id': eid, 'filename': r['filename'], 'characters': []})
        per[eid]['characters'].append({'name': r['name'], 'aliases': json.loads(r['aliases_json'] or '[]')})
        cur_hash[eid] = r['narration_hash'] or cur_hash.get(eid, '')
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT id, characters_reviewed FROM episodes WHERE project_id = ?;", (project_id,))
        _flags = {r['id']: r['characters_reviewed'] for r in cur.fetchall()}
    _common = _get_project_character_names(project_id)
    out = []
    for eid, ep in per.items():
        ep['narration_count'] = seg_counts.get(eid, 0)
        ep['cached'] = bool(cur_hash.get(eid))
        ep['reviewed_flag'] = _flags.get(eid)
        _names = [(c.get('name') or '').strip().lower() for c in ep['characters']]
        if _flags.get(eid) == 1:
            ep['reviewed'] = True
            ep['reviewed_auto'] = False
        elif _flags.get(eid) == 0:
            ep['reviewed'] = False
            ep['reviewed_auto'] = False
        else:
            _auto = bool(_names) and bool(_common) and all(n in _common for n in _names)
            ep['reviewed'] = _auto
            ep['reviewed_auto'] = _auto
        out.append(ep)
    return out

# ── Episodes ──────────────────────────────────────────────────

def get_episode(project_id: str, episode_id: str) -> dict | None:
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM episodes WHERE id = ? AND project_id = ?;", (episode_id, project_id))
        er = cur.fetchone()
        if not er:
            return None

        cur.execute("SELECT * FROM segments WHERE episode_id = ? ORDER BY index_num ASC;", (episode_id,))
        seg_rows = cur.fetchall()
        segments = [{
            "index": sr['index_num'],
            "start_time": sr['start_time'],
            "end_time": sr['end_time'],
            "narration": sr['narration'],
            "tts_duration": sr['tts_duration'] or 0,
            "shot_count": sr['shot_count'] or 0
        } for sr in seg_rows]

        return _row_to_episode(er, segments=segments)

def add_episode_to_project(project_id: str, filename: str, video_path: str, options: dict) -> dict:
    eid = str(uuid.uuid4())[:8]
    now_iso = datetime.now().isoformat()
    options_json = json.dumps(options or {}, ensure_ascii=False)

    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM projects WHERE id = ?;", (project_id,))
        if not cur.fetchone():
            raise ValueError("Project not found")

        cur.execute("""
            INSERT INTO episodes (
                id, project_id, filename, video_path, options_json,
                status, progress, message, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, 'Chờ xử lý', ?);
        """, (eid, project_id, filename, video_path, options_json, now_iso))

        # Đăng ký video gốc vào media_assets
        if video_path and os.path.isfile(video_path):
            cur.execute("""
                INSERT OR IGNORE INTO media_assets (episode_id, project_id, asset_type, file_path, file_size, created_at)
                VALUES (?, ?, 'source_video', ?, ?, ?);
            """, (eid, project_id, video_path, os.path.getsize(video_path), now_iso))

        cur.execute("UPDATE projects SET updated_at = ? WHERE id = ?;", (now_iso, project_id))

    return {
        "id": eid,
        "project_id": project_id,
        "filename": filename,
        "video_path": video_path,
        "options": options or {},
        "status": "pending",
        "progress": 0,
        "message": "Chờ xử lý",
        "result_url": None,
        "srt_url": None,
        "error": None,
        "created_at": now_iso,
        "completed_at": None,
        "segments": []
    }

def update_episode(project_id: str, episode_id: str, updates: dict) -> dict | None:
    if not updates:
        return get_episode(project_id, episode_id)

    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM episodes WHERE id = ? AND project_id = ?;", (episode_id, project_id))
        er = cur.fetchone()
        if not er:
            return None

        # Build dynamic update query
        fields = []
        vals = []
        
        column_map = {
            'status': 'status',
            'progress': 'progress',
            'message': 'message',
            'error': 'error',
            'result_url': 'result_url',
            'srt_url': 'srt_url',
            'manual_prompt': 'manual_prompt',
            'manual_result': 'manual_result',
            'manual_compressed_url': 'manual_compressed_url',
            'num_segments': 'num_segments',
            'target_words': 'target_words',
            'target_sec': 'target_sec',
            'est_sec': 'est_sec',
            'tts_sec': 'tts_sec',
            'task_id': 'task_id',
            'completed_at': 'completed_at',
        }

        for k, col in column_map.items():
            if k in updates:
                fields.append(f"{col} = ?")
                vals.append(updates[k])

        if 'options' in updates:
            fields.append("options_json = ?")
            vals.append(json.dumps(updates['options'] or {}, ensure_ascii=False))

        # Tự động set completed_at nếu status='completed' và chưa có completed_at
        if updates.get('status') == 'completed' and not er['completed_at'] and 'completed_at' not in updates:
            now_iso = datetime.now().isoformat()
            fields.append("completed_at = ?")
            vals.append(now_iso)

        if fields:
            vals.extend([episode_id, project_id])
            cur.execute(f"UPDATE episodes SET {', '.join(fields)} WHERE id = ? AND project_id = ?;", vals)
            # Cập nhật thời gian sửa đổi gần nhất của Series/Project cha
            cur.execute("UPDATE projects SET updated_at = ? WHERE id = ?;", (datetime.now().isoformat(), project_id))

        # Xử lý cập nhật segments
        if 'segments' in updates:
            new_segs = updates['segments']
            # Xóa segments cũ trong DB & FTS
            cur.execute("DELETE FROM segments WHERE episode_id = ?;", (episode_id,))
            cur.execute("DELETE FROM segments_fts WHERE episode_id = ?;", (episode_id,))

            if new_segs and isinstance(new_segs, list):
                for idx, seg in enumerate(new_segs):
                    raw_st = seg.get('start_time') if isinstance(seg, dict) else getattr(seg, 'start_time', None)
                    raw_et = seg.get('end_time') if isinstance(seg, dict) else getattr(seg, 'end_time', None)
                    st_str, st_sec = _parse_time_val(raw_st)
                    et_str, et_sec = _parse_time_val(raw_et)
                    narration = (seg.get('narration', '') if isinstance(seg, dict) else getattr(seg, 'narration', '')) or ''
                    tts_duration = (seg.get('tts_duration', 0) if isinstance(seg, dict) else getattr(seg, 'tts_duration', 0)) or 0
                    shot_count = (seg.get('shot_count', 0) if isinstance(seg, dict) else getattr(seg, 'shot_count', 0)) or 0

                    cur.execute("""
                        INSERT INTO segments (episode_id, index_num, start_time, end_time, start_seconds, end_seconds, narration, tts_duration, shot_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (episode_id, idx, st_str, et_str, st_sec, et_sec, narration, tts_duration, shot_count))

                    if narration.strip():
                        time_range = f"{st_str} --> {et_str}"
                        cur.execute("""
                            INSERT INTO segments_fts (narration, episode_id, project_id, time_range)
                            VALUES (?, ?, ?, ?);
                        """, (narration, episode_id, project_id, time_range))

        # Tự động đồng bộ media_assets cho kết quả mới xuất
        now_ts = datetime.now().isoformat()
        if updates.get('result_url'):
            p = _resolve_url_to_path(updates['result_url'])
            if p and os.path.isfile(p):
                cur.execute("""
                    INSERT OR REPLACE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                    VALUES (?, ?, 'final_video', ?, ?, ?, ?);
                """, (episode_id, project_id, p, updates['result_url'], os.path.getsize(p), now_ts))

        if updates.get('srt_url'):
            p = _resolve_url_to_path(updates['srt_url'])
            if p and os.path.isfile(p):
                cur.execute("""
                    INSERT OR REPLACE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                    VALUES (?, ?, 'final_srt', ?, ?, ?, ?);
                """, (episode_id, project_id, p, updates['srt_url'], os.path.getsize(p), now_ts))

        if updates.get('manual_compressed_url'):
            p = _resolve_url_to_path(updates['manual_compressed_url'])
            if p and os.path.isfile(p):
                cur.execute("""
                    INSERT OR REPLACE INTO media_assets (episode_id, project_id, asset_type, file_path, url_path, file_size, created_at)
                    VALUES (?, ?, 'manual_compressed', ?, ?, ?, ?);
                """, (episode_id, project_id, p, updates['manual_compressed_url'], os.path.getsize(p), now_ts))

    return get_episode(project_id, episode_id)

def delete_episode(project_id: str, episode_id: str) -> bool:
    """Xóa một tập phim khỏi project."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM episodes WHERE id = ? AND project_id = ?;", (episode_id, project_id))
        if not cur.fetchone():
            return False
        cur.execute("DELETE FROM episodes WHERE id = ? AND project_id = ?;", (episode_id, project_id))
        cur.execute("DELETE FROM segments_fts WHERE episode_id = ?;", (episode_id,))
        cur.execute("UPDATE projects SET updated_at = ? WHERE id = ?;", (datetime.now().isoformat(), project_id))
        return True

def reset_episode(project_id: str, episode_id: str):
    """Đặt lại trạng thái tập về pending để retry."""
    return update_episode(project_id, episode_id, {
        "status": "pending",
        "progress": 0,
        "message": "Chờ xử lý (đã đặt lại)",
        "error": None,
        "result_url": None,
        "srt_url": None,
        "segments": [],
        "completed_at": None,
    })

def reset_stuck_episodes():
    """Tự động khôi phục các tập bị kẹt ở trạng thái running/queueing khi server khởi động lại về pending."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE episodes
            SET status = 'pending',
                progress = 0,
                message = 'Chờ xử lý (đã khôi phục sau khi server khởi động)'
            WHERE status IN ('running', 'queueing');
        """)

# ── Multimedia Asset Catalog & Search ─────────────────────────

def register_media_asset(file_path: str, asset_type: str, episode_id: str = None,
                         project_id: str = None, url_path: str = None,
                         duration: float = 0.0, is_temporary: bool = False) -> int:
    """Đăng ký hoặc cập nhật một tệp đa phương tiện vào bảng media_assets."""
    if not file_path or not os.path.exists(file_path):
        return 0
    size = os.path.getsize(file_path)
    now_iso = datetime.now().isoformat()

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO media_assets (
                episode_id, project_id, asset_type, file_path, url_path,
                file_size, duration, is_temporary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                episode_id = COALESCE(excluded.episode_id, media_assets.episode_id),
                project_id = COALESCE(excluded.project_id, media_assets.project_id),
                asset_type = excluded.asset_type,
                url_path = COALESCE(excluded.url_path, media_assets.url_path),
                file_size = excluded.file_size,
                duration = excluded.duration;
        """, (episode_id, project_id, asset_type, file_path, url_path, size, duration, 1 if is_temporary else 0, now_iso))
        return cur.lastrowid or 1

def get_media_assets(episode_id: str = None, project_id: str = None, asset_type: str = None, limit: int = 100) -> list[dict]:
    """Truy vấn danh mục tài nguyên media theo tập, theo phim hoặc theo loại."""
    with get_db_cursor(commit=False) as cur:
        query = "SELECT * FROM media_assets WHERE 1=1"
        params = []
        if episode_id:
            query += " AND episode_id = ?"
            params.append(episode_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if asset_type:
            query += " AND asset_type = ?"
            params.append(asset_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def cleanup_orphan_files(delete: bool = False) -> dict:
    """Quét các file trên đĩa đối chiếu với cơ sở dữ liệu để phát hiện và dọn file mồ côi.
    Nếu delete=True, thực hiện xóa các tệp mồ côi này và giải phóng dung lượng đĩa."""
    known_paths = set()
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT file_path FROM media_assets;")
        for r in cur.fetchall():
            if r['file_path']:
                known_paths.add(os.path.normcase(os.path.abspath(r['file_path'])))

    orphans = []
    deleted_count = 0
    freed_bytes = 0
    scan_dirs = [os.path.join(OUTPUT_DIR, 'final'), os.path.join(OUTPUT_DIR, 'manual')]

    for d in scan_dirs:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    fp = os.path.normcase(os.path.abspath(os.path.join(root, f)))
                    # Không xóa các file cấu hình quan trọng trong output
                    if f.endswith('.json') or f.endswith('.db') or f.endswith('.db-wal') or f.endswith('.db-shm') or f.endswith('.bak'):
                        continue
                    if fp not in known_paths:
                        sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
                        orphans.append({"path": fp, "size": sz})
                        if delete and os.path.isfile(fp):
                            try:
                                os.remove(fp)
                                deleted_count += 1
                                freed_bytes += sz
                            except Exception as e:
                                logger.warning(f"Không thể xóa file mồ côi {fp}: {e}")

    return {
        "orphan_count": len(orphans),
        "total_orphan_size_mb": round(sum(o["size"] for o in orphans) / 1024 / 1024, 2),
        "deleted_count": deleted_count if delete else 0,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2) if delete else 0,
        "orphans": orphans[:50]
    }

# ── Task Persistence (Tiến Trình Chạy) ─────────────────────────

def _row_to_task(r) -> dict:
    if not r:
        return None
    options = {}
    try:
        if r['options_json']: options = json.loads(r['options_json'])
    except Exception:
        options = {}
    result = None
    try:
        if r['result_json']: result = json.loads(r['result_json'])
    except Exception:
        result = None
    segments = []
    try:
        if r['segments_json']: segments = json.loads(r['segments_json'])
    except Exception:
        segments = []

    compressed_url = None
    c_path = r['compressed_path']
    if c_path and os.path.exists(c_path):
        try:
            rel = os.path.relpath(c_path, OUTPUT_DIR).replace('\\', '/')
            compressed_url = f'/output/{rel}'
        except Exception:
            pass

    return {
        'id': r['id'],
        'video_name': r['video_name'] or (os.path.basename(r['video_path']) if r['video_path'] else None),
        'video_path': r['video_path'],
        'options': options,
        'status': r['status'],
        'progress': r['progress'],
        'message': r['message'],
        'result': result,
        'error': r['error'],
        'prompt': r['prompt'],
        'compressed_url': compressed_url,
        'created_at': r['created_at'],
        'completed_at': r['completed_at'],
        'target_sec': r['target_sec'],
        'est_sec': r['est_sec'],
        'tts_sec': r['tts_sec'],
        'output_sec': r['output_sec'],
        'segments': segments,
    }

def save_task(task_data: dict):
    """Lưu hoặc cập nhật thông tin một tác vụ vào bảng tasks trong SQLite."""
    if not task_data or not task_data.get('id'):
        return
    tid = task_data['id']
    v_name = task_data.get('video_name') or (os.path.basename(task_data['video_path']) if task_data.get('video_path') else None)
    v_path = task_data.get('video_path')
    opts = task_data.get('options') or {}
    opts_json = json.dumps(opts, ensure_ascii=False) if isinstance(opts, (dict, list)) else str(opts or '{}')
    status = task_data.get('status', 'pending')
    progress = int(task_data.get('progress', 0))
    message = task_data.get('message', '')
    res = task_data.get('result')
    res_json = json.dumps(res, ensure_ascii=False) if res is not None else None
    error = task_data.get('error')
    prompt = task_data.get('prompt')
    c_path = task_data.get('compressed_path')
    created_at = task_data.get('created_at') or datetime.now().isoformat()
    completed_at = task_data.get('completed_at')
    target_sec = task_data.get('target_sec')
    est_sec = task_data.get('est_sec')
    tts_sec = task_data.get('tts_sec')
    output_sec = task_data.get('output_sec')
    segs = task_data.get('segments') or []
    segs_json = json.dumps(segs, ensure_ascii=False) if isinstance(segs, list) else '[]'

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO tasks (
                id, video_name, video_path, options_json, status, progress,
                message, result_json, error, prompt, compressed_path,
                created_at, completed_at, target_sec, est_sec, tts_sec, output_sec, segments_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                video_name = COALESCE(excluded.video_name, tasks.video_name),
                video_path = COALESCE(excluded.video_path, tasks.video_path),
                options_json = excluded.options_json,
                status = excluded.status,
                progress = excluded.progress,
                message = excluded.message,
                result_json = COALESCE(excluded.result_json, tasks.result_json),
                error = excluded.error,
                prompt = COALESCE(excluded.prompt, tasks.prompt),
                compressed_path = COALESCE(excluded.compressed_path, tasks.compressed_path),
                completed_at = COALESCE(excluded.completed_at, tasks.completed_at),
                target_sec = COALESCE(excluded.target_sec, tasks.target_sec),
                est_sec = COALESCE(excluded.est_sec, tasks.est_sec),
                tts_sec = COALESCE(excluded.tts_sec, tasks.tts_sec),
                output_sec = COALESCE(excluded.output_sec, tasks.output_sec),
                segments_json = CASE WHEN excluded.segments_json != '[]' THEN excluded.segments_json ELSE tasks.segments_json END;
        """, (
            tid, v_name, v_path, opts_json, status, progress,
            message, res_json, error, prompt, c_path,
            created_at, completed_at, target_sec, est_sec, tts_sec, output_sec, segs_json
        ))

def get_saved_tasks(status: str = None, limit: int = 200) -> list[dict]:
    """Lấy danh sách các tác vụ được lưu trong SQLite theo thứ tự mới nhất."""
    with get_db_cursor(commit=False) as cur:
        if status:
            cur.execute("SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?;", (status, limit))
        else:
            cur.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?;", (limit,))
        rows = cur.fetchall()
        return [_row_to_task(r) for r in rows]

def get_saved_task(task_id: str) -> dict | None:
    """Lấy chi tiết một tác vụ theo ID từ SQLite."""
    with get_db_cursor(commit=False) as cur:
        cur.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,))
        r = cur.fetchone()
        return _row_to_task(r) if r else None

def delete_saved_task(task_id: str) -> bool:
    """Xóa một tác vụ khỏi SQLite."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tasks WHERE id = ?;", (task_id,))
        return cur.rowcount > 0

def clear_finished_tasks() -> int:
    """Xóa tất cả các tác vụ đã kết thúc (completed/failed/cancelled) khỏi SQLite."""
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tasks WHERE status IN ('completed', 'failed', 'cancelled');")
        return cur.rowcount

def recover_interrupted_tasks() -> int:
    """Đánh dấu các task bị gián đoạn do server tắt đột ngột sang failed."""
    now_iso = datetime.now().isoformat()
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE tasks
            SET status = 'failed',
                message = 'Bị gián đoạn do khởi động lại server',
                error = 'Tiến trình bị ngắt do server tắt hoặc khởi động lại',
                completed_at = ?
            WHERE status IN ('running', 'queueing');
        """, (now_iso,))
        return cur.rowcount

def seed_tasks_from_episodes():
    """Khởi tạo lịch sử tác vụ từ các tập phim đã có nếu bảng tasks còn trống."""
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM tasks;")
            row = cur.fetchone()
            if row and row['cnt'] > 0:
                return
            cur.execute("SELECT * FROM episodes WHERE status IN ('completed', 'failed') ORDER BY created_at DESC LIMIT 50;")
            eps = cur.fetchall()
            for ep in eps:
                tid = ep['task_id'] or (str(uuid.uuid4())[:8])
                res = {'video_url': ep['result_url'], 'srt_url': ep['srt_url']} if ep['result_url'] else None
                cur.execute("""
                    INSERT OR IGNORE INTO tasks (
                        id, video_name, video_path, options_json, status, progress,
                        message, result_json, error, prompt, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    tid, ep['filename'], ep['video_path'], ep['options_json'],
                    ep['status'], ep['progress'], ep['message'],
                    json.dumps(res, ensure_ascii=False) if res else None,
                    ep['error'], ep['manual_prompt'], ep['created_at'], ep['completed_at']
                ))
    except Exception as e:
        logger.warning(f"Lỗi khởi tạo tasks ban đầu: {e}")

# ── App Key-Value Store (Lưu Trữ Trạng Thái Tập Trung) ─────────

def get_app_kv(key: str, default=None):
    """Lấy giá trị JSON từ bảng app_kv trong SQLite."""
    try:
        with get_db_cursor(commit=False) as cur:
            cur.execute("SELECT value_json FROM app_kv WHERE key = ?;", (key,))
            row = cur.fetchone()
            if row and row['value_json']:
                return json.loads(row['value_json'])
    except Exception as e:
        logger.warning(f"Lỗi đọc app_kv '{key}': {e}")
    return default

def set_app_kv(key: str, value) -> bool:
    """Lưu giá trị JSON vào bảng app_kv trong SQLite (nguyên tử, an toàn đa luồng)."""
    try:
        now_iso = datetime.now().isoformat()
        val_json = json.dumps(value, ensure_ascii=False)
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO app_kv (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at;
            """, (key, val_json, now_iso))
        return True
    except Exception as e:
        logger.warning(f"Lỗi ghi app_kv '{key}': {e}")
        return False

_ensure_project_characters_column()

