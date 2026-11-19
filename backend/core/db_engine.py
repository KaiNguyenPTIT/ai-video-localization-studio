import os
import sqlite3
import threading
from contextlib import contextmanager
from .config import DB_DIR

DB_PATH = os.path.join(DB_DIR, 'anime_summarizer.db')
_write_lock = threading.RLock()

def get_connection():
    """Tạo một connection mới với SQLite, cấu hình WAL mode và timeout phù hợp cho đa luồng."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

@contextmanager
def get_db_cursor(commit=False):
    """Context manager cung cấp cursor và quản lý transaction an toàn giữa các thread."""
    if commit:
        with _write_lock:
            conn = get_connection()
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    else:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            conn.close()

def _ensure_column(cur, table: str, column: str, ddl: str):
    """Thêm cột cho bảng ĐÃ TỒN TẠI (CREATE TABLE IF NOT EXISTS không mở rộng cột khi DB cũ)."""
    cols = {r['name'] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def init_db():
    """Khởi tạo toàn bộ cấu trúc bảng và FTS5 cho Multimedia Database nếu chưa có."""
    with get_db_cursor(commit=True) as cur:
        # 1. Bảng projects
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                settings_json TEXT DEFAULT '{}',
                characters_json TEXT DEFAULT '[]'
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at DESC);")

        # 2. Bảng episodes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                video_path TEXT NOT NULL,
                options_json TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                result_url TEXT,
                srt_url TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                manual_prompt TEXT,
                manual_result TEXT,
                manual_compressed_url TEXT,
                num_segments INTEGER DEFAULT 0,
                target_words INTEGER DEFAULT 0,
                target_sec REAL,
                est_sec REAL,
                tts_sec REAL,
                task_id TEXT,
                characters_reviewed INTEGER DEFAULT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);")

        # 3. Bảng segments
        cur.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                index_num INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                start_seconds REAL DEFAULT 0.0,
                end_seconds REAL DEFAULT 0.0,
                narration TEXT NOT NULL,
                tts_duration REAL DEFAULT 0.0,
                shot_count INTEGER DEFAULT 0,
                voice_speed REAL DEFAULT 1.0,
                audio_path TEXT,
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_segments_episode ON segments(episode_id, index_num);")

        # 4. Bảng media_assets (Media Asset Catalog)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS media_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT,
                project_id TEXT,
                asset_type TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                url_path TEXT,
                file_size INTEGER DEFAULT 0,
                duration REAL DEFAULT 0.0,
                hash_sha256 TEXT,
                is_temporary INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_assets_episode ON media_assets(episode_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_assets_type ON media_assets(asset_type);")

        # 5. Bảng tasks (Lưu vết tiến trình chạy)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                video_name TEXT,
                video_path TEXT,
                options_json TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                result_json TEXT,
                error TEXT,
                prompt TEXT,
                compressed_path TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                target_sec REAL,
                est_sec REAL,
                tts_sec REAL,
                output_sec REAL,
                segments_json TEXT DEFAULT '[]'
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")

        # 6. Bảng ảo FTS5 tìm kiếm toàn văn kịch bản/phụ đề
        try:
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                    narration,
                    episode_id UNINDEXED,
                    project_id UNINDEXED,
                    time_range UNINDEXED,
                    tokenize='unicode61'
                );
            """)
        except Exception:
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                    narration,
                    episode_id UNINDEXED,
                    project_id UNINDEXED,
                    time_range UNINDEXED
                );
            """)

        # 7. Bảng Key-Value lưu trữ trạng thái ứng dụng tập trung (tránh file JSON rải rác)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 8a. Bảng nhân vật THEO TẬP: cache trích xuất Gemini của từng tập (narration_hash để
        # biết kịch bản đã đổi chưa — đổi thì tự trích lại). Danh sách "đã duyệt" của cả
        # dự án vẫn nằm ở projects.characters_json (registry đưa vào prompt).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS episode_characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                name TEXT NOT NULL,
                aliases_json TEXT DEFAULT '[]',
                narration_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (episode_id, name),
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_epchars_project ON episode_characters(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_epchars_episode ON episode_characters(episode_id);")

        # 8. Mở rộng cột cho DB CŨ (nâng cấp lưu trữ thời lượng TTS + shot count theo cảnh)
        _ensure_column(cur, 'episodes', 'characters_reviewed', 'INTEGER DEFAULT NULL')
        _ensure_column(cur, 'episodes', 'target_sec', 'REAL')
        _ensure_column(cur, 'episodes', 'est_sec', 'REAL')
        _ensure_column(cur, 'episodes', 'tts_sec', 'REAL')
        _ensure_column(cur, 'segments', 'tts_duration', 'REAL DEFAULT 0.0')
        _ensure_column(cur, 'segments', 'shot_count', 'INTEGER DEFAULT 0')
        _ensure_column(cur, 'tasks', 'tts_sec', 'REAL')
