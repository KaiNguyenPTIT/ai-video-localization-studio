import uuid, time, os, queue
from datetime import datetime, timedelta
from threading import Thread, Lock
from .config import OUTPUT_DIR, MAX_INFLIGHT_EPISODES


def _segment_dict(s) -> dict:
    """Chuyển Segment (hoặc dict đã có sẵn) sang dict đầy đủ cho API/DB:
    kèm tts_duration (thời lượng lời bình thật sau TTS) và shot_count
    (số shot dùng cho cảnh sau bước cắt shot)."""
    return {
        'index':         getattr(s, 'index', 0),
        'start_time':    s.start_time if hasattr(s, 'start_time') else (s.get('start_time') if isinstance(s, dict) else ''),
        'end_time':      s.end_time if hasattr(s, 'end_time') else (s.get('end_time') if isinstance(s, dict) else ''),
        'narration':     s.narration if hasattr(s, 'narration') else (s.get('narration') if isinstance(s, dict) else ''),
        'tts_duration':  round(float(getattr(s, 'tts_duration', 0) or 0), 3),
        'shot_count':    int(getattr(s, 'shot_count', 0) or 0) if hasattr(s, 'shot_count') else int((s or {}).get('shot_count', 0)),
    }

class Task:
    def __init__(self, task_id, video_path, options):
        self.id           = task_id
        self.video_path   = video_path
        self.video_name   = os.path.basename(video_path) if video_path else None
        self.options      = options
        self.status       = 'pending'
        self.progress     = 0
        self.message      = 'Khởi tạo...'
        self.result       = None
        self.error        = None
        self.segments     = []
        self.compressed_path = None
        self.prompt       = None
        self.result_text  = None
        self.on_update    = None
        self.created_at   = datetime.now().isoformat()
        self.completed_at = None
        self.target_sec   = None  # mục tiêu (DETAIL_LEVELS) — biết ngay khi chạy
        self.est_sec      = None  # ước lượng đọc theo kịch bản AI — sau bước Gemini
        self.tts_sec      = None  # thời lượng THẬT của lời bình (Σ tts_duration) — sau bước TTS
        self.output_sec   = None  # độ dài thật video tóm tắt — khi hoàn tất
        self._cancelled   = False
        self._procs       = []   # ffmpeg/subprocess đang chạy của task — để kill khi hủy
        self._procs_lock  = Lock()
        self._tmp_paths   = []   # file/thư mục trung gian cần dọn khi hủy

    def register_proc(self, proc):
        with self._procs_lock:
            self._procs.append(proc)

    def unregister_proc(self, proc):
        with self._procs_lock:
            try:
                self._procs.remove(proc)
            except ValueError:
                pass

    def kill_procs(self):
        """Kill tất cả subprocess đang chạy của task — cho hủy ngắt cứng ffmpeg giữa chừng."""
        with self._procs_lock:
            procs, self._procs = list(self._procs), []
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass

    def to_dict(self, include_segments: bool = True, include_prompt: bool = True):
        compressed_url = None
        if self.compressed_path and os.path.exists(self.compressed_path):
            try:
                rel = os.path.relpath(self.compressed_path, OUTPUT_DIR).replace('\\', '/')
                compressed_url = f'/output/{rel}'
            except ValueError:
                pass
        data = {
            'id':             self.id,
            'video_name':     self.video_name or (os.path.basename(self.video_path) if self.video_path else None),
            'video_path':     self.video_path,
            'options':        self.options,
            'status':         self.status,
            'progress':       self.progress,
            'message':        self.message,
            'result':         self.result,
            'error':          self.error,
            'created_at':     self.created_at,
            'completed_at':   self.completed_at,
            'compressed_url': compressed_url,
            'target_sec':     self.target_sec,
            'est_sec':        self.est_sec,
            'tts_sec':        self.tts_sec,
            'output_sec':     self.output_sec,
        }
        if include_prompt:
            data['prompt'] = self.prompt
        if include_segments:
            data['segments'] = [
                _segment_dict(s) if hasattr(s, 'start_time') else s
                for s in (self.segments or [])
            ]
        return data

    @classmethod
    def from_dict(cls, d: dict):
        t = cls(d['id'], d.get('video_path'), d.get('options') or {})
        t.video_name = d.get('video_name')
        t.status = d.get('status', 'pending')
        t.progress = d.get('progress', 0)
        t.message = d.get('message', '')
        t.result = d.get('result')
        t.error = d.get('error')
        t.prompt = d.get('prompt')
        t.created_at = d.get('created_at') or datetime.now().isoformat()
        t.completed_at = d.get('completed_at')
        t.target_sec = d.get('target_sec')
        t.est_sec = d.get('est_sec')
        t.tts_sec = d.get('tts_sec')
        t.output_sec = d.get('output_sec')
        t.segments = d.get('segments') or []
        return t


class TaskManager:
    def __init__(self):
        self.tasks        = {}
        self._lock        = Lock()
        self.worker_queue = queue.Queue()
        self._init_from_db()
        self._start_worker()
        self._start_cleanup()

    def _init_from_db(self):
        """Khôi phục các task gần nhất từ SQLite vào RAM khi khởi động."""
        try:
            from . import database
            database.recover_interrupted_tasks()
            database.seed_tasks_from_episodes()
            rows = database.get_saved_tasks(limit=150)
            with self._lock:
                for d in rows:
                    t = Task.from_dict(d)
                    self.tasks[t.id] = t
        except Exception:
            pass

    def _persist(self, task):
        """Lưu trạng thái task vào SQLite."""
        try:
            from . import database
            database.save_task(task.to_dict())
        except Exception:
            pass

    # ── Workers: nhiều tập vào NỀN, nhưng từng loại nguồn lực tự siết ≤2 ─
    def _start_worker(self):
        """Số worker = số tập được VÀO NỀN (MAX_INFLIGHT_EPISODES).
        Đây KHÔNG còn là giới hạn độ song song từng bước: mạng bị siết bằng
        NETWORK_EPISODE_LOCK (≤2), phần cứng bằng LOCAL_HARDWARE_LOCK (≤1)."""
        from .key_pool import get_keys
        n = max(1, min(MAX_INFLIGHT_EPISODES, len(get_keys())))
        for _ in range(n):
            Thread(target=self._worker_loop, daemon=True).start()
        self._num_workers = n

    def _worker_loop(self):
        while True:
            task, fn = self.worker_queue.get()
            if not task._cancelled:
                self._execute_task(task, fn)
            self.worker_queue.task_done()

    def _execute_task(self, task, fn):
        try:
            task.status = 'running'
            self._persist(task)
            if task.on_update:
                task.on_update()
            fn(task)
            if not task._cancelled:
                task.status       = 'completed'
                task.progress     = 100
                task.message      = 'Hoàn tất video tóm tắt!'
                task.completed_at = datetime.now().isoformat()
            else:
                task.status  = 'cancelled'
                task.message = 'Đã hủy bởi người dùng'
        except Exception as e:
            if '__CANCELLED__' in str(e) or task._cancelled:
                task.status  = 'cancelled'
                task.message = 'Đã hủy bởi người dùng'
                task.error   = None
            else:
                task.status  = 'failed'
                task.error   = str(e)
                task.message = f'Lỗi: {e}'
        finally:
            self._persist(task)
            if task.on_update:
                task.on_update()

    def force_cancel(self, task_id: str) -> bool:
        """Hủy task dù đang queueing hay running — dùng khi xóa episode."""
        t = self.tasks.get(task_id)
        if not t:
            return False
        t._cancelled = True
        t.kill_procs()  # ngắt cứng: kill ffmpeg đang chạy nếu có
        if t.status in ('queueing', 'pending'):
            t.status  = 'cancelled'
            t.message = 'Đã hủy bởi người dùng'
            self._persist(t)
            if t.on_update:
                t.on_update()
        # Nếu đang running: _cancelled=True sẽ bị bắt bởi check_cancel() trong pipeline
        return True

    # ── Cleanup: Xóa task cũ hơn 24h khỏi RAM ──────────────────
    def _start_cleanup(self):
        def _cleaner():
            while True:
                time.sleep(3600)  # Mỗi 1 giờ dọn 1 lần
                cutoff = datetime.now() - timedelta(hours=24)
                with self._lock:
                    old = [tid for tid, t in self.tasks.items()
                           if t.status in ('completed', 'failed', 'cancelled')
                           and datetime.fromisoformat(t.created_at) < cutoff]
                    for tid in old:
                        del self.tasks[tid]
        Thread(target=_cleaner, daemon=True).start()

    # ── Public API ──────────────────────────────────────────────
    def create_task(self, video_path, options):
        t = Task(str(uuid.uuid4())[:8], video_path, options)
        with self._lock:
            self.tasks[t.id] = t
        self._persist(t)
        return t

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def list_tasks(self):
        return list(self.tasks.values())

    def run_task(self, task, fn):
        task.status   = 'queueing'
        task.message  = 'Đang chờ worker xử lý...'
        task._cancelled = False
        self._persist(task)
        if task.on_update:
            task.on_update()
        self.worker_queue.put((task, fn))

    def scale_workers(self):
        """Giữ số worker theo MAX_INFLIGHT_EPISODES (nhiều tập nền);
        độ song song từng bước do NETWORK_EPISODE_LOCK + LOCAL_HARDWARE_LOCK quyết định."""
        from .key_pool import get_keys
        n_target = max(1, min(MAX_INFLIGHT_EPISODES, len(get_keys())))
        current  = getattr(self, '_num_workers', 1)
        for _ in range(max(0, n_target - current)):
            Thread(target=self._worker_loop, daemon=True).start()
        self._num_workers = max(current, n_target)

    def cancel_task(self, task_id):
        """Hủy task đang queueing (không thể hủy task đang running)."""
        t = self.tasks.get(task_id)
        if not t:
            return False
        if t.status == 'queueing':
            t._cancelled = True
            t.status     = 'cancelled'
            t.message    = 'Đã hủy bởi người dùng'
            self._persist(t)
            if t.on_update:
                t.on_update()
            return True
        return False

    def recover_interrupted_tasks(self):
        """Cập nhật trạng thái các task bị ngắt do khởi động lại server."""
        try:
            from . import database
            count = database.recover_interrupted_tasks()
            with self._lock:
                for t in self.tasks.values():
                    if t.status in ('running', 'queueing'):
                        t.status = 'failed'
                        t.message = 'Bị gián đoạn do khởi động lại server'
                        t.error = 'Tiến trình bị ngắt do server tắt hoặc khởi động lại'
            return count
        except Exception:
            return 0

    def delete_task(self, task_id):
        """Xóa task khỏi bộ nhớ và SQLite (chỉ áp dụng cho task đã kết thúc)."""
        t = self.tasks.get(task_id)
        if t and t.status in ('running', 'queueing'):
            return False
        with self._lock:
            self.tasks.pop(task_id, None)
        try:
            from . import database
            database.delete_saved_task(task_id)
        except Exception:
            pass
        return True

    def clear_finished(self) -> int:
        """Xóa tất cả các tác vụ đã kết thúc khỏi RAM và SQLite."""
        with self._lock:
            finished = [tid for tid, t in self.tasks.items() if t.status in ('completed', 'failed', 'cancelled')]
            for tid in finished:
                self.tasks.pop(tid, None)
        try:
            from . import database
            return database.clear_finished_tasks()
        except Exception:
            return len(finished)

    def get_stats(self):
        """Thống kê nhanh trạng thái hàng đợi."""
        tasks = list(self.tasks.values())
        return {
            'total':     len(tasks),
            'running':   sum(1 for t in tasks if t.status == 'running'),
            'queueing':  sum(1 for t in tasks if t.status == 'queueing'),
            'completed': sum(1 for t in tasks if t.status == 'completed'),
            'failed':    sum(1 for t in tasks if t.status == 'failed'),
        }


task_manager = TaskManager()
