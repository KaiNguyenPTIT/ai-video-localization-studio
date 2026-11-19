import os, subprocess, requests, base64, threading, logging, hashlib

logger = logging.getLogger(__name__)
from backend.core.config import AUDIO_DIR, CACHE_DIR, VOICES, LOCAL_HARDWARE_LOCK


def _short_err(err, limit: int = 300) -> str:
    """Rút gọn lỗi để hiển thị UI/log: cắt signed URL dài của CapCut CDN.

    URL tải MP3 chứa query ký tên dài ~500 ký tự — hiện nguyên văn sẽ tràn UI
    và lộ token. Chỉ giữ lại host + loại lỗi + 300 ký tự đầu."""
    import re as _re
    s = str(err or '').strip()
    # Thay mọi URL http(s) dài bằng host của nó (vd https://v16-cc.capcut.com/...)
    def _host_only(m):
        url = m.group(0)
        host = _re.sub(r'^https?://', '', url).split('/')[0]
        return f'[{host}/...]'
    s = _re.sub(r'https?://[^\s\'")]+', _host_only, s)
    # Cắt query còn sót (a=...&bti=...) nếu không phải URL đầy đủ
    s = _re.sub(r'\?(?:a|bti|bt|ft|mime_type|rc|vvpl|l|btag)=[^\s]*', ' [tham số ký tên đã ẩn]', s)
    if len(s) > limit:
        s = s[:limit].rstrip() + '…'
    return s or type(err).__name__

class TTSEngine:
    def __init__(self, voice_key: str = '', ref_audio: str = None, ref_text: str = None, speed: float = None):
        if not voice_key or voice_key not in VOICES:
            voice_key = next(iter(VOICES), '')
        self.voice_key = voice_key
        self.voice_info = VOICES.get(voice_key)
        if not self.voice_info:
            raise RuntimeError('Không có giọng đọc nào khả dụng')
        self.voice_type = self.voice_info.get('type', 'capcut')
        self.voice_id = self.voice_info.get('id', '')
        # Giọng mẫu cho OmniVoice-clone, ưu tiên: tham số truyền vào (mẫu theo phim)
        # → ref gắn sẵn trong giọng thư viện (giọng custom/dựng sẵn).
        self.ref_audio = ref_audio or self.voice_info.get('ref_audio')
        self.ref_text = ref_text if ref_text else (self.voice_info.get('ref_text') or '')
        # Tốc độ đọc: ưu tiên tham số gọi → speed gắn trong giọng → biến VOICESTUDIO_SPEED toàn cục.
        # Clamp vào [0.5, 2.0] để không vượt giới hạn API VoiceStudio.
        from backend.core.config import VOICESTUDIO_SPEED as _VS_SPEED
        _raw_speed = speed if speed is not None else (
            self.voice_info.get('speed') if self.voice_info.get('speed') is not None else _VS_SPEED
        )
        self.speed = max(0.5, min(2.0, float(_raw_speed or 1.0)))
        # Tái dùng 1 CapCutClient/Session cho mọi segment trong cùng lượt TTS:
        # requests.Session giữ keep-alive + connection pool, tránh bắt tay TLS mới
        # mỗi segment (tốn hàng giây trên mạng chậm tới editor-api-sg). Session của
        # requests an toàn khi dùng đồng thời từ nhiều thread.
        self._capcut_client = None
        self._capcut_lock = threading.Lock()

    def synthesize(self, text: str, output_path: str) -> float:
        text = text.strip()
        if not text: return 0.0
        if self.voice_type == 'voicestudio':
            return self._synthesize_voicestudio(text, output_path)
        # Chỉ dùng CapCut — retry tối đa 3 lần (delay 1.5s→3s), không fallback sang giọng khác
        import time as _time
        last_err = None
        for attempt in range(3):
            try:
                if self._synthesize_capcut(text, output_path):
                    return self.get_duration(output_path)
                # API không trả URL / HTTP lỗi: coi như 1 lần thử thất bại, giữ lý do rõ
                last_err = RuntimeError('CapCut API không trả về URL audio (mạng bận hoặc CapCut bận)')
            except Exception as e:
                last_err = e
                logger.warning(f"[TTS] CapCut thử {attempt + 1}/3 thất bại ({self.voice_key}): {_short_err(e)}")
            if attempt < 2:
                _time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(
            f'CapCut TTS thất bại sau 3 lần thử (không fallback). '
            f'Lỗi cuối: {_short_err(last_err)}. '
            f'Kiểm tra mạng tới CapCut hoặc chuyển sang giọng VoiceStudio local.'
        )

    def _synthesize_voicestudio(self, text: str, output_path: str) -> float:
        from .voicestudio_service import synthesize as _vs_synth
        vid = str(self.voice_id or 'default')
        return _vs_synth(text, output_path, voice=vid, speed=self.speed)


    def _get_capcut_client(self):
        from .capcut_tts_api import CapCutClient
        if self._capcut_client is None:
            with self._capcut_lock:
                if self._capcut_client is None:
                    self._capcut_client = CapCutClient()
        return self._capcut_client

    def _synthesize_capcut(self, text: str, output_path: str) -> bool:
        client = self._get_capcut_client()
        resource_id = self.voice_info.get('resource_id') or None
        try:
            res = client.create_multi_platform_tts(
                texts=[text], voice=self.voice_id, resource_id=resource_id, rate='1.0'
            )
        except Exception as e:
            # Không nuốt lỗi tạo task — ném tiếp để synthesize() retry + ghi log rõ
            raise RuntimeError(f'Lỗi tạo task TTS CapCut: {_short_err(e)}') from e
        url = None
        if res:
            mats = ((res.get('data') or {}).get('tts_materials') or [])
            for m in mats:
                md = m.get('meta_data') or {}
                url = md.get('url') or (m.get('extra_map') or {}).get('url_office')
                if url:
                    break
        if not url:
            return False
        # Tải MP3 từ CDN (v16-cc.capcut.com...): connect fail-fast 10s để không treo
        # 60s/mỗi attempt khi mạng nghẽn; read giữ 60s cho file chậm. Dùng chung
        # session keep-alive của client để đỡ bắt tay TLS lại. Lỗi tải ném tiếp
        # để vòng retry ngoài thử lại (tạo URL mới mỗi lần).
        try:
            sess = getattr(client, 'session', None)
            if sess is not None:
                resp = sess.get(url, timeout=(10, 60))
            else:
                import requests as _req
                resp = _req.get(url, timeout=(10, 60))
        except Exception as e:
            raise RuntimeError(f'Lỗi tải audio CapCut: {_short_err(e)}') from e
        if resp.status_code != 200:
            return False
        with open(output_path, 'wb') as f:
            f.write(resp.content)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 100

    def _synthesize_edge(self, text: str, output_path: str, voice: str) -> bool:
        raise RuntimeError('Edge TTS đã bị loại bỏ — chỉ hỗ trợ VoiceStudio (local) và CapCut (cloud).')

    @staticmethod
    def get_duration(audio_path: str) -> float:
        try:
            with LOCAL_HARDWARE_LOCK:
                res = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path], capture_output=True, text=True, check=True)
            return float(res.stdout.strip())
        except:
            return max(1.0, os.path.getsize(audio_path) / 16000.0)

def generate_all_tts(segments: list, voice_key: str = None, progress_callback=None, work_dir=None, is_cancelled=None, ref_audio: str = None, ref_text: str = None, speed: float = None) -> list:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    tts = TTSEngine(voice_key=voice_key or '', ref_audio=ref_audio, ref_text=ref_text, speed=speed)
    total = len(segments)
    if total == 0:
        return segments
    if is_cancelled and is_cancelled():
        raise RuntimeError('__CANCELLED__')
    if tts.voice_type == 'voicestudio':
        return _generate_all_tts_voicestudio(segments, tts, progress_callback, work_dir, is_cancelled)
    # TTS gọi API ngoài (CapCut) nên I/O-bound -> song song an toàn RAM, chạy nhanh hơn nhiều.
    # NHƯNG phải chặn trần: workers=total (vd 75 segment = 75 thread) dội burst vào
    # editor-api + CDN v16-cc.capcut.com gây ConnectTimeout hàng loạt. 5 luồng song song
    # là điểm cân bằng tốc độ/ổn định đã kiểm chứng với timeout API 45s.
    workers = min(max(1, total), 5)
    lock = threading.Lock()
    done_count = 0

    def do_one(i):
        nonlocal done_count
        if is_cancelled and is_cancelled():
            raise RuntimeError('__CANCELLED__')
        seg = segments[i]
        out_path = os.path.join(work_dir or AUDIO_DIR, f'tts_{seg.index:03d}.mp3')
        seg.tts_audio_path = out_path
        try:
            seg.tts_duration = tts.synthesize(seg.narration, out_path)
        except Exception as e:
            # Thêm ngữ cảnh segment để log/UI biết đoạn nào hỏng (không lộ nội dung dài)
            raise RuntimeError(f'Segment #{getattr(seg, "index", i)}: {e}') from e
        with lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Đang tạo giọng đọc [{cur}/{total}]', 40 + int((cur / total) * 20))
        return i

    # Dùng submit + as_completed (thay vì map) để phát hiện hủy NGAY khi có segment
    # rảnh, đồng thời cancel các future còn đang chờ. Request HTTP đang chạy (≤ ~60s)
    # không ngắt giữa chừng được, nhưng không đưa segment mới vào.
    ex = ThreadPoolExecutor(max_workers=workers)
    futures = [ex.submit(do_one, i) for i in range(total)]
    try:
        for fut in as_completed(futures):
            if is_cancelled and is_cancelled():
                for f in futures:
                    f.cancel()
                raise RuntimeError('__CANCELLED__')
            fut.result()
    except BaseException:
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return segments


# Semaphore TOÀN CỤC cho synth VoiceStudio local (không phải mạng): tổng cộng tối đa
# 2 request đồng thời tới localhost:3900 dù có mấy tập/mấy worker — tránh dội burst
# vào server local gây 429/503 dây chuyền. Tách khỏi NETWORK_EPISODE_LOCK (dành cho API cloud).
VOICESTUDIO_GLOBAL_SEM = threading.Semaphore(2)
VOICESTUDIO_WORKERS = 2


def _generate_all_tts_voicestudio(segments: list, tts: 'TTSEngine', progress_callback=None, work_dir=None, is_cancelled=None) -> list:
    """TTS local (VoiceStudio): 2 luồng song song qua HTTP API tới localhost:3900.

    Server tổng hợp mỗi câu độc lập nên song song không đổi chất lượng giọng —
    tổng giờ ≈ một nửa so với chạy tuần tự (đo thực tế để xác nhận server có song
    song thật hay serialize ngầm). Mỗi segment retry 3 lần kiểu CapCut (delay tăng
    dần) để 429 thoáng qua không fail cả tập."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = len(segments)
    if total == 0:
        return segments
    if is_cancelled and is_cancelled():
        raise RuntimeError('__CANCELLED__')
    lock = threading.Lock()
    done_count = 0

    def do_one(i):
        nonlocal done_count
        if is_cancelled and is_cancelled():
            raise RuntimeError('__CANCELLED__')
        seg = segments[i]
        out_path = os.path.join(work_dir or AUDIO_DIR, f'tts_{seg.index:03d}.mp3')
        seg.tts_audio_path = out_path
        last_err = None
        for attempt in range(3):
            if is_cancelled and is_cancelled():
                raise RuntimeError('__CANCELLED__')
            try:
                with VOICESTUDIO_GLOBAL_SEM:
                    seg.tts_duration = tts.synthesize(seg.narration, out_path)
                break
            except Exception as e:
                last_err = e
                logger.warning(f"[TTS] VoiceStudio thử {attempt + 1}/3 thất bại "
                               f"(segment #{getattr(seg, 'index', i)}): {_short_err(e)}")
                if attempt < 2:
                    import time as _time
                    _time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f'Segment #{getattr(seg, "index", i)}: {last_err}')
        with lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Đang tạo giọng đọc VoiceStudio [{cur}/{total}] (speed={tts.speed:.2f}x)', 40 + int((cur / total) * 20))
        return i

    workers = min(max(1, total), VOICESTUDIO_WORKERS)
    ex = ThreadPoolExecutor(max_workers=workers)
    futures = [ex.submit(do_one, i) for i in range(total)]
    try:
        for fut in as_completed(futures):
            if is_cancelled and is_cancelled():
                for f in futures:
                    f.cancel()
                raise RuntimeError('__CANCELLED__')
            fut.result()
    except BaseException:
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return segments


def warm_voicestudio(timeout: float = 60.0) -> bool:
    """Hâm nóng server VoiceStudio bằng 1 câu tổng hợp ngắn (hút cold-start load model
    khỏi segment đầu tiên của tập). Trả True nếu server đáp. Không ném exception."""
    try:
        from .voicestudio_service import check_health, synthesize as _vs_synth
        ok, _ = check_health(timeout=2.0)
        if not ok:
            return False
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tf:
            tmp = tf.name
        try:
            _vs_synth('Xin chào.', tmp, voice='default', speed=1.0)
            return os.path.isfile(tmp) and os.path.getsize(tmp) > 100
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception as e:
        logger.warning(f'[TTS] Không hâm nóng được VoiceStudio: {_short_err(e)}')
        return False



PREVIEW_TEXT = "Xin chào, đây là giọng đọc thử của công cụ tóm tắt anime!"

# Khóa theo từng giọng để 2 click cùng lúc không gọi API trùng (click sau chờ click trước).
_preview_locks: dict[str, threading.Lock] = {}
_preview_locks_guard = threading.Lock()


def _preview_lock_for(voice_key: str) -> threading.Lock:
    with _preview_locks_guard:
        lock = _preview_locks.get(voice_key)
        if lock is None:
            lock = threading.Lock()
            _preview_locks[voice_key] = lock
        return lock


def _valid_preview(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 100
    except OSError:
        return False


def preview_voice(voice_key: str, text: str = None) -> str:
    """Tạo audio nghe thử cho 1 giọng, trả về đường dẫn file mp3.

    text rỗng → đọc câu demo cố định (cache chung preview_<voice>.mp3).
    text riêng (tối đa 200 ký tự) → cache theo hash câu (preview_<voice>_<hash>.mp3).
    Cache đĩa: CapCut (cloud) → trả ngay nếu file còn hợp lệ, không gọi lại API.
    VoiceStudio (local) → LUÔN tạo lại: xóa file cũ trước khi tổng hợp để phản ánh
    đúng giọng/tốc độ hiện tại (speed, model có thể thay đổi giữa các lần nhấn nghe thử)."""
    say = (text or '').strip()[:200] or PREVIEW_TEXT
    preview_dir = os.path.join(CACHE_DIR, 'preview')
    os.makedirs(preview_dir, exist_ok=True)
    if say == PREVIEW_TEXT:
        out_path = os.path.join(preview_dir, f'preview_{voice_key}.mp3')
    else:
        digest = hashlib.sha1(say.encode('utf-8')).hexdigest()[:10]
        out_path = os.path.join(preview_dir, f'preview_{voice_key}_{digest}.mp3')

    voice_info = VOICES.get(voice_key) or {}
    is_voicestudio = voice_info.get('type') == 'voicestudio'

    # CapCut: dùng cache đĩa để tránh gọi cloud lặp lại.
    # VoiceStudio: bỏ qua cache — xóa file cũ trước để luôn tổng hợp mới.
    if is_voicestudio:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass
    elif _valid_preview(out_path):
        return out_path

    with _preview_lock_for(os.path.basename(out_path)):
        # CapCut: click khác có thể đã tạo xong trong lúc chờ khóa.
        if not is_voicestudio and _valid_preview(out_path):
            return out_path
        tts = TTSEngine(voice_key=voice_key)
        tts.synthesize(say, out_path)
        if not _valid_preview(out_path):
            raise RuntimeError('Không tạo được audio nghe thử cho giọng này')
        return out_path


def warm_preview_cache(max_voices: int = 0) -> int:
    """Nạp sẵn file nghe thử cho mọi giọng CapCut (gọi lúc server khởi động, nền).

    max_voices<=0: làm hết. Bỏ qua giọng lỗi, không ném exception. Trả về số file có sẵn."""
    try:
        keys = list(VOICES.keys())
    except Exception:
        return 0
    if max_voices and max_voices > 0:
        keys = keys[:max_voices]
    ready = 0
    for key in keys:
        # Bỏ qua giọng local (VoiceStudio): để lazy khi người dùng bấm nghe thử hoặc chạy tập
        if (VOICES.get(key) or {}).get('type') == 'voicestudio':
            continue
        try:
            preview_voice(key)
            ready += 1
        except Exception as e:
            logger.warning(f"[TTS] Không nạp sẵn được giọng {key}: {e}")
    return ready
