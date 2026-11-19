import os, threading, time

_env_path = None
_lock = threading.Lock()
_rr = 0          # vòng tròn round-robin để mỗi request dùng key khác nhau

# Key lỗi (429/503/504/timeout...) tự vào cooldown để các lượt gọi sau BỎ QUA,
# khỏi cày lại key treo 30-60s mỗi lần. Hết hạn tự dùng lại (lỗi có thể chỉ tạm thời).
KEY_COOLDOWN_SEC = float(os.getenv('GEMINI_KEY_COOLDOWN_SEC', '600'))
_COOLDOWN_KV = 'gemini_key_cooldown'
_cooldown_mem: dict = {}


def _normalize(keys):
    out = []
    for k in keys:
        k = (k or '').strip()
        k = k.strip('",\' ')
        if k:
            out.append(k)
    # loại trùng key trùng
    seen = set()
    uniq = []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def get_keys():
    """Đọc danh sách key từ env `GEMINI_API_KEY` (nhiều key cách nhau dấu phẩy).
    Không tạo key mới — chỉ trả về key đã được lưu. Nếu không có key nào -> [].
    """
    raw = os.getenv('GEMINI_API_KEY', '')
    return _normalize(raw.split(','))


def set_keys(keys):
    """Cập nhật danh sách key (danh sách chuỗi) và ghi ngược vào .env."""
    global _env_path
    uniq = _normalize(keys)
    with _lock:
        os.environ['GEMINI_API_KEY'] = ','.join(uniq)
        _write_env(','.join(uniq))
    return uniq


def _write_env(value):
    global _env_path
    path = _env_path
    if not path:
        from .config import BASE_DIR
        path = os.path.join(BASE_DIR, '.env')
        _env_path = path
    try:
        lines = []
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
        new_lines, replaced = [], False
        for ln in lines:
            if ln.strip().startswith('GEMINI_API_KEY='):
                new_lines.append(f'GEMINI_API_KEY={value}')
                replaced = True
            else:
                new_lines.append(ln)
        if not replaced:
            new_lines.append(f'GEMINI_API_KEY={value}')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines) + '\n')
    except Exception:
        pass


def _load_cooldown() -> dict:
    """Gộp cooldown RAM + SQLite app_kv (restart vẫn nhớ key nào đang lỗi)."""
    merged = dict(_cooldown_mem)
    try:
        from . import database
        data = database.get_app_kv(_COOLDOWN_KV, {})
        if isinstance(data, dict):
            now = time.time()
            for k, v in data.items():
                try:
                    exp = float(v)
                except (TypeError, ValueError):
                    continue
                if exp > now and exp > merged.get(k, 0):
                    merged[k] = exp
    except Exception:
        pass
    return merged


def _save_cooldown(d: dict):
    _cooldown_mem.clear()
    _cooldown_mem.update(d)
    try:
        from . import database
        now = time.time()
        database.set_app_kv(_COOLDOWN_KV, {k: v for k, v in d.items() if v > now})
    except Exception:
        pass


def record_key_result(key: str, ok: bool):
    """Ghi nhận kết quả 1 lượt gọi: ok → xóa cooldown; lỗi → cooldown KEY_COOLDOWN_SEC."""
    if not key:
        return
    with _lock:
        d = _load_cooldown()
        if ok:
            d.pop(key, None)
        else:
            d[key] = time.time() + KEY_COOLDOWN_SEC
        _save_cooldown(d)


def get_usable_keys() -> list:
    """Danh sách key trừ các key đang cooldown. Nếu TẤT CẢ đều cooldown thì trả
    toàn bộ (thà thử chậm còn hơn deadlock không key nào để gọi)."""
    keys = get_keys()
    if not keys:
        return []
    with _lock:
        d = _load_cooldown()
        now = time.time()
        fresh = [k for k in keys if d.get(k, 0) <= now]
    return fresh or keys


def reverse_keys():
    """Đảo ngược thứ tự key trong env GEMINI_API_KEY và ghi ngược vào .env —
    để chạy được các key đang nằm ở CUỐI danh sách (chưa được dùng). Chạy lại lần nữa = khôi phục."""
    keys = get_keys()
    if not keys:
        return []
    return set_keys(list(reversed(keys)))


def next_key():
    """Trả key kế tiếp theo vòng tròn (mỗi request một key khác nhau). Nếu hết key -> None."""
    keys = get_keys()
    if not keys:
        return None
    global _rr
    with _lock:
        idx = _rr % len(keys)
        _rr += 1
    return keys[idx]


def rotate(key):
    """Sau khi key gặp lỗi, xoay vòng sang key khác (không lặp vô hạn)."""
    keys = get_keys()
    if not keys:
        return None
    if len(keys) == 1:
        return None
    with _lock:
        try:
            cur = keys.index(key)
        except ValueError:
            cur = -1
        return keys[(cur + 1) % len(keys)]
