import os, subprocess, ctypes, hashlib, json, logging, random, contextlib, contextvars, re, threading
from concurrent.futures import ThreadPoolExecutor
from backend.core.config import (
    SEGMENTS_DIR, TEMP_DIR, OUTPUT_RESOLUTION, OUTPUT_FPS, LOCAL_HARDWARE_LOCK,
    OUTPUT_DIR, CACHE_DIR, OUTPUT_VIDEO_BITRATE, OUTPUT_VIDEO_MAXRATE, OUTPUT_VIDEO_CQ,
    OUTPUT_NVENC_PRESET, OUTPUT_GOP_SECONDS, OUTPUT_AUDIO_BITRATE, OUTPUT_AUDIO_RATE,
    SHOT_SCENE_THRESHOLD, SHOT_MIN_DURATION, SHOT_MAX_DURATION,
    SHOT_DETECTOR, PYSCENE_METHOD, PYSCENE_ADAPTIVE_THRESHOLD, PYSCENE_MIN_CONTENT_VAL,
    PYSCENE_CONTENT_THRESHOLD, PYSCENE_MIN_SCENE_LEN, PYSCENE_FRAME_SKIP,
    PYSCENE_BACKEND, PYSCENE_USE_PROXY, MANUAL_DIR, SHOT_MERGE_MIN,
    SEARCH_WINDOW_BEFORE, SEARCH_WINDOW_AFTER, MIN_CLIP_DURATION, MAX_CLIP_DURATION,
    MAX_REUSE_DISTANCE, VOICE_SYNC_TOLERANCE, SKIP_INTRO_OUTRO,
    INTRO_SKIP_SECONDS, OUTRO_SKIP_SECONDS, SMART_SHOT_ALTERNATE_FLIP,
    SMART_SHOT_ZOOM_PERCENT,     SMART_SHOT_SPEED_MIN, SMART_SHOT_SPEED_MAX, SMART_SHOT_SHUFFLE,
    SMART_SHOT_REVERSE, SHOT_REVERSE_MAX_SEC, REVERSE_CHUNK_SEC,
)

logger = logging.getLogger(__name__)

_CORES = os.cpu_count() or 4


def _available_ram_gb() -> float:
    """RAM khả dụng (GB) của hệ thống, dùng để điều chỉnh số tiến trình ffmpeg song song."""
    try:
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 1e9
    except Exception:
        return 4.0


def compute_concurrency():
    """Số tiến trình ffmpeg nén nên chạy song song, theo RAM khả dụng (không tràn RAM) + CPU.

    Ước lượng ~1.3GB RAM mỗi tiến trình encode 1080p. Luôn >= 1.
    """
    ram_based = max(1, int(_available_ram_gb() / 1.3))
    return max(1, min(_CORES, ram_based))


def _threads_for(concurrency: int) -> str:
    """Số khung (threads) cho mỗi ffmpeg để không oversubscribe CPU."""
    if concurrency <= 1:
        return '0'  # auto = dùng hết cores
    return str(max(1, _CORES // concurrency))


_FFMPEG_TIMEOUT = 300  # giây; chống treo vô hạn khi decode file lớn/x265

# Ngữ cảnh hủy của task đang chạy — cho phép `run_ffmpeg`/detect_shots biết task bị hủy
# giữa chừng và đăng ký subprocess để `force_cancel` kill ngay (hủy ngắt cứng).
# ContextVar truyền tự động sang ThreadPoolExecutor (mỗi worker copy context lúc submit).
_FFMPEG_CANCEL_CTX = contextvars.ContextVar('ffmpeg_cancel_ctx', default=None)


@contextlib.contextmanager
def ffmpeg_cancel_context(is_cancelled, register, unregister):
    """Đặt ngữ cảnh hủy cho toàn bộ công việc ffmpeg trong pipeline thread hiện tại."""
    token = _FFMPEG_CANCEL_CTX.set({'is_cancelled': is_cancelled, 'register': register, 'unregister': unregister})
    try:
        yield
    finally:
        _FFMPEG_CANCEL_CTX.reset(token)


def _pool_session_init(is_cancelled, register, unregister):
    """Initializer cho ThreadPoolExecutor của render/cut: đặt ngữ cảnh hủy trong TỪNG worker
    (Python 3.13 KHÔNG copy contextvars vào worker thread pool — phải đặt thủ công per-worker)."""
    _FFMPEG_CANCEL_CTX.set({'is_cancelled': is_cancelled, 'register': register, 'unregister': unregister})


def _cancelled_error():
    raise RuntimeError('__CANCELLED__')


def _cancellable_run(cmd: list, timeout: int):
    """subprocess.run có thể bị hủy giữa chừng: đăng ký Popen vào ngữ cảnh để force_cancel
    kill được; nếu task hủy trong lúc chạy → ném __CANCELLED__ thay vì chờ xong."""
    ctx = _FFMPEG_CANCEL_CTX.get()
    if ctx and ctx['is_cancelled']():
        _cancelled_error()  # đã hủy từ trước → không spawn thêm lệnh nào
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if ctx:
        ctx['register'](proc)
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            if ctx and ctx['is_cancelled']():
                _cancelled_error()
            raise RuntimeError(f'FFmpeg timeout sau {timeout}s: {" ".join(cmd[-4:])}')
        if ctx and ctx['is_cancelled']():
            _cancelled_error()
        if proc.returncode != 0:
            raise RuntimeError(f'FFmpeg loi: {err[-300:]}')
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout=out, stderr=err)
    finally:
        if ctx:
            ctx['unregister'](proc)


def run_ffmpeg(cmd: list, timeout: int = _FFMPEG_TIMEOUT, lock: bool = True):
    """Chạy ffmpeg. `lock=False` cho phép nhiều tiến trình encode NVENC chạy SONG SONG
    (bước render sau khi có kịch bản) — GPU encode giải phóng CPU/RAM so với libx264.
    Các lệnh probe/CPU vẫn giữ lock mặc định để phần cứng không bị oversubscribe.
    Hỗ trợ hủy ngắt cứng: nếu task bị hủy giữa lệnh, subprocess bị kill ngay."""
    if lock:
        with LOCAL_HARDWARE_LOCK:
            return _cancellable_run(cmd, timeout)
    return _cancellable_run(cmd, timeout)


# Tham số NVENC cho RENDER (output cuối) — VBR + CQ (mặc định 5M/max 8M/CQ26/preset p3).
# VBR+CQ: cảnh tĩnh (anime thoại, màu bẹt) tự tụt bitrate → file nhẹ ~40% so với CBR 8M cứng;
# cảnh hành động vẫn bung tới maxrate nên không mờ. Preset p3 nén tốt hơn p1 ~20-30%
# mà tốc độ GPU vẫn nhanh. Chỉnh ở Admin → Encoding, có hiệu lực ngay.
# GOP = FPS × OUTPUT_GOP_SECONDS (mặc định 2s = 60 frames @ 30fps) để tua chính xác.
def _nvenc_v_tail(pix_fmt: bool = True) -> list:
    gop = max(int(OUTPUT_FPS) * OUTPUT_GOP_SECONDS, int(OUTPUT_FPS))  # tối thiểu 1s GOP
    tail = ['-c:v', 'h264_nvenc', '-preset', str(OUTPUT_NVENC_PRESET),
            '-rc', 'vbr', '-cq', str(int(OUTPUT_VIDEO_CQ)),
            '-b:v', OUTPUT_VIDEO_BITRATE,
            '-maxrate', OUTPUT_VIDEO_MAXRATE, '-bufsize', OUTPUT_VIDEO_MAXRATE,
            '-g', str(gop), '-keyint_min', str(gop), '-sc_threshold', '0',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    if not pix_fmt:
        tail = [a for a in tail if a not in ('-pix_fmt', 'yuv420p', '-movflags', '+faststart')]
    return tail


def _render_concurrency() -> int:
    """Số luồng cắt/ghép NVENC song song — tự siết theo RAM khả dụng (không tràn RAM).
    NVENC decode CPU ~0.8GB/luồng (nhẹ hơn encode libx264 1.3GB). Mỗi segment độc lập
    nên tăng workers không đổi 1 pixel output. Cap 3 (máy 16GB RAM + RTX: 3×0.8GB
    + buffer reverse vẫn vừa)."""
    try:
        avail = _available_ram_gb()
    except Exception:
        avail = 4.0
    if avail < 2.5:
        return 1
    if avail < 7.0:
        return 2
    return 3


# Semaphore riêng cho ffprobe CHỈ-ĐỌC (không đụng GPU): trước đây probe chen chung
# LOCAL_HARDWARE_LOCK với encode/nén/detect nên TTS + render block lẫn nhau hàng phút.
# Probe không dùng phần cứng → cap nhẹ 8 concurrent là đủ, bỏ lock toàn cục.
_PROBE_SEMAPHORE = threading.BoundedSemaphore(8)

# Cache duration trong RAM: cùng 1 file trung gian đang bị probe 3-4 lần
# (_ok → _concat total_in/out_dur → _merge v_dur). Key theo size+mtime nên file
# ghi lại là tự miss. Chỉ cache giá trị > 0 (probe lỗi không poison cache).
_DUR_CACHE: dict = {}
_DUR_CACHE_LOCK = threading.Lock()


def _dur_cache_key(video_path: str):
    try:
        st = os.stat(video_path)
        return f'{os.path.abspath(video_path)}|{st.st_size}|{int(st.st_mtime)}'
    except OSError:
        return None


_REAL_DUR_CACHE = {}

def get_video_duration(video_path: str) -> float:
    """Duration ghi trong CONTAINER. Trả 0.0 nếu không đọc được (không crash 'N/A').
    Có cache RAM theo size+mtime; probe chỉ-đọc nên dùng semaphore riêng, không giữ
    LOCAL_HARDWARE_LOCK (tránh block encode/nén/detect)."""
    key = _dur_cache_key(video_path)
    if key:
        with _DUR_CACHE_LOCK:
            hit = _DUR_CACHE.get(key)
        if hit:
            return hit
    try:
        with _PROBE_SEMAPHORE:
            res = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path], capture_output=True, text=True, check=True)
        val = float(res.stdout.strip())
    except Exception:
        return 0.0
    if key and val > 0:
        with _DUR_CACHE_LOCK:
            _DUR_CACHE[key] = val
    return val


def _probe_packet_end(video_path: str) -> float:
    """Độ dài NGUỒN THẬT (giây) = pts video packet cuối cùng.

    Container MKV/MP4 có thể khai duration lớn hơn lượng data THỰC (file bị cụt/
    tải dở). Lúc đó mọi timestamp sau điểm cụt đều cắt ra clip rỗng → merge lỗi
    'could not convert string to float: N/A'. Probe theo packet (không decode)
    để clamp kịch bản vào phần các frame THỰC SỰ tồn tại. Trả 0 nếu không lấy được.
    """
    try:
        with _PROBE_SEMAPHORE:
            res = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', video_path],
                capture_output=True, text=True)
        best = 0.0
        for line in (res.stdout or '').splitlines():
            line = line.strip()
            if not line or line == 'N/A':
                continue
            try:
                v = float(line)
            except ValueError:
                continue
            if v > best:
                best = v
        return best
    except Exception:
        return 0.0


def get_real_video_duration(video_path: str) -> float:
    """Duration khả dụng THẬT = min(container, video packet cuối).

    Có cache theo video → chỉ probe 1 lần. Ai đó upload file cụt thì duration
    thật nhỏ hơn container: pipeline dùng cái này để kịch bản không vượt quá
    phần video thực sự có hình.
    """
    try:
        st = os.stat(video_path)
        key = f'{os.path.abspath(video_path)}|{st.st_size}|{int(st.st_mtime)}'
    except OSError:
        return 0.0
    if key in _REAL_DUR_CACHE:
        return _REAL_DUR_CACHE[key]
    container = get_video_duration(video_path)
    real = _probe_packet_end(video_path)
    dur = container
    if real > 0 and (container <= 0 or real < container - 0.5):
        dur = real
        logger.warning(f"[DUR] {os.path.basename(video_path)}: container={container:.1f}s "
                       f"nhưng data video thực chỉ {real:.1f}s (file cụt?) — dùng {dur:.1f}s")
    _REAL_DUR_CACHE[key] = dur
    return dur


def get_video_size(video_path: str):
    """Trả về (width, height) của luồng video đầu tiên; (0, 0) nếu không lấy được."""
    with _PROBE_SEMAPHORE:
        res = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                               '-show_entries', 'stream=width,height',
                               '-of', 'default=noprint_wrappers=1', video_path],
                              capture_output=True, text=True)
    w = h = 0
    for line in res.stdout.splitlines():
        k, _, v = line.partition('=')
        if k == 'width':
            w = int(v)
        elif k == 'height':
            h = int(v)
    return w, h


def compress_video_for_upload(video_path: str, output_path: str, height: int = 480, use_gpu: bool = True, keep_audio: bool = False, fps: int = 0, light: bool = False, cq: str = None, audio_bitrate: str = None):
    """Nén video gốc thành MP4 H.264 (giữ nguyên thời lượng) — HÀM LÕI DUY NHẤT của hệ thống.

    Dùng chung cho mọi đường nén (gửi Gemini API, upload AI Studio, prepare manual,...).
    Chỉ đổi resolution, KHÔNG đổi tốc độ/duration -> timestamp Gemini trả vẫn khớp với video gốc.
    keep_audio=True: giữ lại luồng audio (dùng cho mode thủ công người xem đối chiếu thoại);
    keep_audio=False: bỏ audio để giảm kích thước (Gemini API chỉ cần nhìn hình ảnh).
    fps>0: giảm/set tốc độ khung (càng thấp càng nhẹ, vd 12); fps<=0: giữ nguyên FPS nguồn.
    light=True: nén mạnh hơn (cq/crf cao) dành cho upload API — file nhỏ ~1/2
    giúp upload nhanh, chất lượng vẫn đủ cho Gemini hiểu nội dung.
    cq: ghi đè mức nén NVENC (nếu truyền); ngược lại mặc định theo light.
    audio_bitrate: bitrate audio nếu keep_audio (vd '64k'); mặc định 96k.
    Ưu tiên tối ưu bằng GPU (decode CUVID + scale_cuda + NVENC), fallback dần về CPU.
    """
    w, h = OUTPUT_RESOLUTION
    src_w, src_h = get_video_size(video_path)
    # tính width chẵn theo height (scale_cuda không hỗ trợ -2)
    if src_w and src_h:
        target_w = int(round(src_w * height / src_h))
        target_w = target_w - (target_w % 2)  # làm chẵn
        target_w = max(2, target_w)
    else:
        target_w = -2

    audio = ['-c:a', 'aac', '-b:a', audio_bitrate] if (keep_audio and audio_bitrate) else (['-c:a', 'aac'] if keep_audio else ['-an'])
    fps_args = ['-r', str(fps)] if (fps or 0) > 0 else []
    nvenc_cq = cq or ('40' if light else '30')
    cpu_crf = '42' if light else '35'

    if use_gpu:
        gpu_cmds = [
            # 1) Toàn bộ trên GPU: CUVID decode + scale_cuda + NVENC (format yuv420p để NVENC chấp nhận)
            ['ffmpeg', '-y', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', video_path,
             '-vf', f'scale_cuda=w={target_w}:h={height}:format=yuv420p'] + audio + fps_args + [
             '-c:v', 'h264_nvenc', '-preset', 'p1', '-cq', nvenc_cq,
             '-movflags', '+faststart', output_path],
            # 2) GPU decode nhưng scale bằng CPU (một phần GPU)
            ['ffmpeg', '-y', '-hwaccel', 'cuda', '-i', video_path,
             '-vf', f'scale=-2:{height},format=yuv420p'] + audio + fps_args + [
             '-c:v', 'h264_nvenc', '-preset', 'p1', '-cq', nvenc_cq,
             '-movflags', '+faststart', output_path],
            # 3) GPU decode tự động
            ['ffmpeg', '-y', '-hwaccel', 'auto', '-i', video_path,
             '-vf', f'scale=-2:{height},format=yuv420p'] + audio + fps_args + [
             '-c:v', 'h264_nvenc', '-preset', 'p1', '-cq', nvenc_cq,
             '-movflags', '+faststart', output_path],
        ]
        for cmd in gpu_cmds:
            try:
                run_ffmpeg(cmd)
                return output_path
            except Exception:
                continue
    cmd = ['ffmpeg', '-y', '-threads', '0', '-i', video_path,
           '-vf', f'scale=-2:{height}'] + audio + fps_args + [
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', cpu_crf,
           '-movflags', '+faststart', output_path]
    run_ffmpeg(cmd)
    return output_path


def make_studio_upload_copy(video_path: str, max_mb: float, out_path: str):
    """Ép video xuống ≤ max_mb cho upload AI Studio (Playwright CDP không set_files
    được file >50MB). Dùng CHUNG lõi compress_video_for_upload (GPU NVENC, giữ audio,
    giữ fps nguồn) — chỉ lặp tăng cq nếu vẫn quá dung lượng. Trả về out_path nếu thành công."""
    # Các mức cq tăng dần (nhỏ = nét hơn nhưng to hơn). Luôn giữ audio + fps nguồn + 480p.
    attempts = [('64k', '38'), ('64k', '43'), ('48k', '47')]
    tmp = os.path.splitext(out_path)[0] + '.tmp.mp4'
    for abit, cq in attempts:
        for f in (tmp, out_path):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        try:
            compress_video_for_upload(video_path, tmp, height=480, keep_audio=True, cq=cq,
                                      audio_bitrate=abit, fps=12)
        except Exception:
            continue
        if os.path.exists(tmp) and 0 < os.path.getsize(tmp) <= max_mb * 1024 * 1024:
            os.replace(tmp, out_path)
            return out_path
    raise RuntimeError(f'Không nén video xuống ≤{max_mb:.0f}MB để upload AI Studio.')


def cut_and_fit_segment(video_path: str, start: float, end: float, target_duration: float, output_path: str, threads: str = '0', lock: bool = True, flip: bool = False, zoom_center: tuple = None, speed: float = 1.0, reverse: bool = False):
    dur = max(0.5, end - start)
    w, h = OUTPUT_RESOLUTION
    base = f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black'
    if flip:
        base = 'hflip,' + base
    # Zoom 125% (SMART_SHOT_ZOOM_PERCENT): phóng khung vừa scale/pad lên, crop lại về w x h
    # tại MỘT vị trí ngẫu nhiên (tạo nhịp chuyển cảnh không bị tĩnh khi nối nhiều shot).
    if SMART_SHOT_ZOOM_PERCENT > 100 and zoom_center:
        zx, zy = zoom_center
        # Diện tích phóng: crop về kích thước = w/z rồi scale lên w x h → hiệu ứng zoom z lần.
        z = SMART_SHOT_ZOOM_PERCENT / 100.0
        cw = int(w / z)
        ch = int(h / z)
        cw -= cw % 2  # cần chẵn cho yuv420p/h264
        ch -= ch % 2
        if cw > 0 and ch > 0:
            zx = max(0, min(zx, w - cw))
            zy = max(0, min(zy, h - ch))
            base = f'{base},crop={cw}:{ch}:{zx}:{zy},scale={w}:{h}'
    if reverse:
        # Chạy NGƯỢC clip (từ cuối về đầu). reverse đặt SAU scale để buffer nhỏ; PTS sau
        # reverse không tăng dần nên phải reset bằng setpts dạng N-based (khuyên của ffmpeg).
        # Dùng FRAME_RATE của input (không hardcode 30) để giữ đúng thời lượng với mọi fps
        # nguồn (vd. anime 12fps). Tốc độ vẫn áp dụng được trong cùng biểu thức.
        vf = f'{base},reverse,setpts=N/(FRAME_RATE*{max(1.0, speed):.6f}*TB)'
    elif speed > 1.0:
        # Tăng tốc phát lại (setpts=1/speed) — nguồn vào dài hơn speed lần nhưng output giữ
        # đúng dur → video chuyển động nhanh, thời lượng ngắn clip không đổi.
        # Trừ STARTPTS để gốc PTS luôn về 0: clip nối stream-copy sau này không bị lệch
        # base PTS (từng gây video dài sai khi concat copy). Toán học tương đương PTS/S.
        vf = f'setpts=(PTS-STARTPTS)/{speed:.6f},{base}'
    else:
        vf = base
    vf += ',format=yuv420p'
    tail = ['-vf', vf, '-an', '-r', str(OUTPUT_FPS)] + _nvenc_v_tail() + [output_path]

    def _ok():
        # File PHẢI có duration > 0 (có frame video thật). File 262B chỉ header
        # (video cụt/đoạn vượt data thực) xuất hiện khi ffmpeg cắt đúng chỗ không
        # có frame — dùng size>0 sẽ nhận nhầm là thành công rồi merge ra 'N/A'.
        if not (os.path.exists(output_path) and os.path.getsize(output_path) > 0):
            return False
        if get_video_duration(output_path) > 0:
            return True
        try:
            os.remove(output_path)
        except Exception:
            pass
        return False

    # 1. Cắt nhanh bằng input seeking (-ss trước -i) + giới hạn input (-t trước -i)
    #    với GPU decode. -t PHẢI nằm trước -i (input option) với MỌI chế độ:
    #    (a) filter `reverse` chỉ nhả frame khi gặp EOF input — -t sau -i (output
    #        option) khiến ffmpeg đọc CẢ FILE vào buffer → OOM, clip ra sai đoạn;
    #    (b) với speed>1 (setpts /S), -t sau -i đếm theo OUTPUT: muxer cứ đòi đủ dur
    #        giây output nên demuxer đọc tới S²×dur nguồn (vượt xa kế hoạch S× của
    #        edit plan, ăn lấn sang cảnh khác) — -t trước -i khóa đúng phạm vi plan.
    #    x265/HEVC 10-bit decode CPU rất chậm; d3d11va decode GPU ổn định cả khi chạy
    #    SONG SONG (cuda/NVDEC decode 10-bit song song bị lỗi "streams received no packets").
    gpu_cmds = [
        ['ffmpeg', '-y', '-threads', threads, '-hwaccel', 'd3d11va',
         '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', video_path] + tail,
        ['ffmpeg', '-y', '-threads', threads, '-hwaccel', 'auto',
         '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', video_path] + tail,
    ]
    made = False
    for cmd in gpu_cmds:
        try:
            res = run_ffmpeg(cmd, lock=lock)
            if res.returncode != 0:
                continue
            if _ok():
                made = True
                break
        except Exception:
            continue

    # 2. Fallback: input seeking CPU thuần (không GPU decode)
    if not made:
        cmd = ['ffmpeg', '-y', '-threads', threads, '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', video_path] + tail
        run_ffmpeg(cmd, lock=lock)
        made = _ok()

    # 3. Cuối cùng: nếu vẫn chưa có file, thử accurate seeking (-ss sau -i) — decode từ
    #    đầu tới mốc cần, chỉ áp dụng khi các cách trên đều thất bại.
    #    (KHÔNG dùng cho reverse: decode từ đầu + reverse = buffer cả file → OOM.)
    if not made and not reverse:
        cmd_fallback = ['ffmpeg', '-y', '-threads', threads, '-hwaccel', 'd3d11va', '-i', video_path, '-ss', f'{start:.3f}', '-t', f'{dur:.3f}'] + tail
        run_ffmpeg(cmd_fallback, lock=lock)
        made = _ok()

    if not made:
        # Không cắt được segment nào (đoạn vượt quá data video thực / file nguồn cụt).
        # Ném lỗi RÕ ràng — không để segment rỗng 262B lọt xuống merge rồi crash 'N/A'.
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        raise RuntimeError(
            f'Không cắt được phân đoạn [{start:.1f}s → {end:.1f}s] — đoạn này nằm ngoài '
            f'phần video thực tế có hình (file nguồn có thể bị cụt/thiếu dữ liệu cuối phim).')


def cut_all_segments(video_path: str, segments: list, progress_callback=None, work_dir=None,
                     is_cancelled=None, register=None, unregister=None):
    import threading
    total = len(segments)
    if total == 0:
        return segments
    duration = get_real_video_duration(video_path)
    # Cắt encode NVENC (GPU) — decode CPU nhẹ, cho phép SONG SONG tối đa 2 luồng tùy RAM.
    concurrency = _render_concurrency()
    threads = _threads_for(concurrency)
    lock = threading.Lock()
    done_count = 0

    def do_one(i):
        nonlocal done_count
        seg = segments[i]
        out_path = os.path.join(work_dir or SEGMENTS_DIR, f'seg_{seg.index:03d}.mp4')
        st = seg.adjusted_start if seg.adjusted_start > 0 else seg.start_seconds
        et = seg.adjusted_end if seg.adjusted_end > 0 else seg.end_seconds
        
        # Đảm bảo phạm vi thời gian hợp lệ trong video gốc
        if et <= st:
            et = st + 2.0
        if et > duration:
            et = duration
        if et <= st:
            st = max(0.0, et - 2.0)

        cut_and_fit_segment(video_path, st, et, seg.tts_duration, out_path, threads, lock=False)
        seg.video_segment_path = out_path
        with lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Cắt phân cảnh video [{cur}/{total}]', 60 + int((cur / total) * 15))
        return i

    with ThreadPoolExecutor(max_workers=concurrency, initializer=_pool_session_init,
                            initargs=(is_cancelled, register, unregister)) as ex:
        list(ex.map(do_one, range(total)))
    return segments


def _merge_one(seg, threads: str, work_dir=None, lock: bool = True):
    out_path = os.path.join(work_dir or TEMP_DIR, f'merged_{seg.index:03d}.mp4')
    v_dur = get_video_duration(seg.video_segment_path)
    if v_dur <= 0:
        # Segment bị rỗng/thời lượng không xác định (file cụt/đoạn vượt data thực).
        # Không để lọt xuống build ffmpeg rồi crash 'could not convert float N/A'.
        raise RuntimeError(
            f'Phân đoạn #{getattr(seg, "index", "?")} không có video hợp lệ '
            f'(duration=0) — file nguồn bị cụt hoặc đoạn cắt nằm ngoài data thực.')
    a_dur = getattr(seg, 'tts_duration', 0) or 0
    if a_dur <= 0:
        a_dur = get_video_duration(seg.tts_audio_path)  # fallback: chưa có duration từ TTS
    if a_dur <= 0:
        return seg.video_segment_path

    speed = max(0.6, min(v_dur / a_dur if v_dur > 0 else 1.0, 1.6))
    v_new = v_dur / speed if speed > 0 else v_dur
    extra = max(0.0, a_dur - v_new)

    # PTS-STARTPTS: reset gốc PTS về 0 để -t a_dur LUÔN cắt đúng từ đầu.
    # Trước đây dùng setpts=ratio*PTS — nếu input có PTS base lệch (do concat -c copy
    # để lại moov/PTS vỡ dưới tải GPU), -t chỉ cắt "thêm a_dur giây sau base" -> clip
    # ra dài = base + a_dur, concat tiếp theo đẩy dần -> video output vượt xa audio.
    # Kèm -r/-fps_mode cfr ép CFR: khung frame đều, timeline liền mạch khi nối.
    if extra > 0.05:
        vf_full = f'[0:v]setpts=(PTS-STARTPTS)*{1/speed:.4f},tpad=stop_mode=clone:stop_duration={extra:.3f},format=yuv420p[v]'
    else:
        vf_full = f'[0:v]setpts=(PTS-STARTPTS)*{1/speed:.4f},format=yuv420p[v]'

    cmd = ['ffmpeg', '-y', '-threads', threads, '-i', seg.video_segment_path, '-i', seg.tts_audio_path,
           '-filter_complex', vf_full, '-map', '[v]', '-map', '1:a',
           '-r', str(OUTPUT_FPS), '-fps_mode', 'cfr',
           ] + _nvenc_v_tail() + [
           '-c:a', 'aac', '-b:a', OUTPUT_AUDIO_BITRATE, '-ar', str(OUTPUT_AUDIO_RATE), '-ac', '2',
           '-t', f'{a_dur:.3f}', out_path]
    run_ffmpeg(cmd, lock=lock)
    return out_path


def _thirds_reorder_enabled():
    from ..core import config
    return bool(getattr(config, 'VIDEO_THIRDS_REORDER', True))


def _concat_clips(paths: list, out_path: str, lock: bool = True):
    """Nối nhiều sub-clip cùng chuẩn (h264_nvenc/yuv420p, không audio) thành 1 clip.
    Thử stream-copy trước (bit-identical, nhanh): mọi part đều do cut_and_fit_segment
    đẻ ra với cùng tham số, PTS đã zero-based, và file kết quả LUÔN được re-encode ở
    bước merge audio sau — nên copy ở đây an toàn tuyệt đối về chất lượng/timeline.
    Validate tổng thời lượng (±1s), lệch/thất bại → fallback re-encode NVENC + CFR."""
    list_file = os.path.join(os.path.dirname(out_path) or '.', f'.{os.path.basename(out_path)}_list.txt')
    with open(list_file, 'w', encoding='utf-8') as f:
        for p in paths:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
    try:
        total_in = 0.0
        for p in paths:
            try:
                total_in += get_video_duration(p)
            except Exception:
                pass
        run_ffmpeg(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
                    '-c', 'copy', '-movflags', '+faststart', out_path], lock=lock)
        out_dur = 0.0
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            try:
                out_dur = get_video_duration(out_path)
            except Exception:
                out_dur = 0.0
        if out_dur > 0 and abs(out_dur - total_in) < 1.0:
            try:
                os.remove(list_file)
            except Exception:
                pass
            return out_path
        logger.warning(f"[CONCAT] Nối copy lệch ({total_in:.1f}s → {out_dur:.1f}s) — fallback re-encode")
    except Exception as e:
        logger.warning(f"[CONCAT] Nối copy thất bại ({e}) — fallback re-encode")
    cmds = [
        ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
         '-r', str(OUTPUT_FPS), '-fps_mode', 'cfr'] + _nvenc_v_tail() + [out_path],
    ]
    last = None
    for cmd in cmds:
        try:
            run_ffmpeg(cmd, lock=lock)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                try:
                    os.remove(list_file)
                except Exception:
                    pass
                return out_path
        except Exception as e:
            last = e
            continue
    try:
        os.remove(list_file)
    except Exception:
        pass
    raise RuntimeError(f'Không ghép được các phần cảnh: {last}')


def _build_three_part_scene(video_path: str, st: float, et: float, out_path: str, threads: str = '0', lock: bool = True):
    """Chia cảnh [st,et] làm 2 phần ĐỀU (P1 = [st, giữa] ngay đầu, P2 = [giữa, et] từ giữa) rồi ghép
    theo thứ tự đổi chỗ P2-P1 (nửa sau lên trước). Cảnh quá ngắn (<1.5s) → giữ nguyên một mảnh liên tục."""
    span = et - st
    if span <= 1.5:
        cut_and_fit_segment(video_path, st, et, span, out_path, threads, lock=lock)
        return out_path
    p = span / 2.0
    base = os.path.dirname(out_path) or '.'
    stem = os.path.basename(out_path)
    parts = []
    try:
        for pos, (s, e) in enumerate(((st, st + p), (st + p, et))):
            tmp = os.path.join(base, f'{stem}.part{pos}.mp4')
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            # Mỗi sub-clip lát đúng 1/2 bằng đúng chuẩn output (scale/pad/fps).
            cut_and_fit_segment(video_path, s, max(e, s + 0.3), e - s, tmp, threads, lock=lock)
            parts.append(tmp)
        if not all(os.path.exists(t) and os.path.getsize(t) > 0 for t in parts):
            raise RuntimeError('Một phần cắt bị rỗng')
        # Thứ tự đầu ra: P2 (nửa sau, từ giữa) → P1 (nửa đầu)
        _concat_clips([parts[1], parts[0]], out_path, lock=lock)
        return out_path
    finally:
        for t in parts:
            try:
                if os.path.exists(t):
                    os.remove(t)
            except Exception:
                pass


def cut_merge_all_segments(video_path: str, segments: list, progress_callback=None, work_dir=None,
                           is_cancelled=None, register=None, unregister=None):
    """Cắt + khớp nối âm thanh từng phân cảnh trong MỘT lượt (thay vì cắt hết → chờ → merge hết).
    Encode NVENC (GPU) — cắt+merge SONG SONG tối đa 2 luồng tùy RAM (mỗi luồng = 1 segment độc lập)."""
    import threading
    total = len(segments)
    if total == 0:
        return []
    concurrency = _render_concurrency()
    threads = _threads_for(concurrency)
    duration = get_real_video_duration(video_path)
    work = [(i, seg) for i, seg in enumerate(segments, 1) if getattr(seg, 'tts_audio_path', None)]
    merged = [None] * len(work)
    done_lock = threading.Lock()
    done_count = 0

    def do_one(idx):
        nonlocal done_count
        i, seg = work[idx]
        out_seg = os.path.join(work_dir or SEGMENTS_DIR, f'seg_{seg.index:03d}.mp4')
        st = seg.adjusted_start if seg.adjusted_start > 0 else seg.start_seconds
        et = seg.adjusted_end if seg.adjusted_end > 0 else seg.end_seconds

        # Bảo đảm phạm vi thời gian hợp lệ trong video gốc
        if et <= st:
            et = st + 2.0 if st + 2.0 <= duration else duration
        if et > duration:
            et = duration
        if et <= st:
            st = max(0.0, et - 2.0)

        if _thirds_reorder_enabled():
            _build_three_part_scene(video_path, st, et, out_seg, threads, lock=False)
        else:
            cut_and_fit_segment(video_path, st, et, getattr(seg, 'tts_duration', 0), out_seg, threads, lock=False)
        seg.video_segment_path = out_seg
        out_merged = _merge_one(seg, threads, work_dir, lock=False)
        with done_lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Cắt & khớp nối [{cur}/{total}]', 60 + int((cur / total) * 28))
        return out_merged

    with ThreadPoolExecutor(max_workers=concurrency, initializer=_pool_session_init,
                            initargs=(is_cancelled, register, unregister)) as ex:
        results = list(ex.map(do_one, range(len(work))))
    return [m for m in results if m]


def merge_all_segments(segments: list, progress_callback=None, work_dir=None,
                       is_cancelled=None, register=None, unregister=None):
    import threading
    work = [seg for seg in segments if seg.video_segment_path and seg.tts_audio_path]
    total = len(work)
    if total == 0:
        return []
    concurrency = _render_concurrency()  # merge encode NVENC (GPU): song song tối đa 2 tùy RAM
    threads = _threads_for(concurrency)
    merged = [None] * total
    lock = threading.Lock()
    done_count = 0

    def do_one(i):
        nonlocal done_count
        seg = work[i]
        merged[i] = _merge_one(seg, threads, work_dir, lock=False)
        with lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Khớp nối âm thanh [{cur}/{total}]', 75 + int((cur / total) * 12))
        return i

    with ThreadPoolExecutor(max_workers=concurrency, initializer=_pool_session_init,
                            initargs=(is_cancelled, register, unregister)) as ex:
        list(ex.map(do_one, range(total)))
    return [p for p in merged if p]



def concat_videos(paths: list, output_path: str, work_dir=None, try_copy_first: bool = False):
    list_file = os.path.join(work_dir or TEMP_DIR, 'concat_list.txt')
    with open(list_file, 'w', encoding='utf-8') as f:
        for p in paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")
    # Re-encode khi nối: CHUẨN HÓA timeline + keyframe đều (-g) để video TUA (seek) được chính xác.
    # Stream-copy concat giữ nguyên flags/GOP từng segment nhỏ -> kết quả thiếu keyframe => không tua được.
    def _clean_list():
        try:
            os.remove(list_file)
        except Exception:
            pass
    if try_copy_first:
        # ── Đường NHANH: TS-based concat (không re-encode) ─────────────────────────
        # Concat demuxer + -c copy thất bại khi bất kỳ file nào có NAL unit lỗi nhỏ
        # (h264_mp4toannexb bị nghẹt → demux error → output ngắn hơn dự kiến → code
        # phát hiện lệch → fallback NVENC, mất 10+ phút cho nhiều tập).
        #
        # TS-based method: remux từng file sang .ts với bsf h264_mp4toannexb (SỬA NAL
        # trước), rồi nối bằng concat: protocol (1 pass). Test thực tế: 11 tập (4758s)
        # ghép trong ~23 giây, thời lượng output đúng, lossless — không encode lại.
        ts_files = []
        try:
            total_in = 0.0
            for p in paths:
                try:
                    total_in += get_video_duration(p)
                except Exception:
                    pass
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

            # Bước 1: remux mỗi MP4 sang TS (sửa NAL, không encode lại)
            for idx, p in enumerate(paths):
                ts_path = os.path.join(work_dir or TEMP_DIR, f'_ts_{idx:03d}.ts')
                run_ffmpeg(['ffmpeg', '-y', '-i', p,
                            '-c', 'copy', '-bsf:v', 'h264_mp4toannexb', ts_path])
                ts_files.append(ts_path)

            # Bước 2: ghép tất cả TS thành 1 MP4 bằng concat: protocol
            concat_input = 'concat:' + '|'.join(ts_files)
            run_ffmpeg(['ffmpeg', '-y', '-i', concat_input,
                        '-c', 'copy', '-movflags', '+faststart', output_path])

            out_dur = 0.0
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    out_dur = get_video_duration(output_path)
                except Exception:
                    out_dur = 0.0
            if out_dur > 0 and abs(out_dur - total_in) < 5.0:
                logger.info(f"[MERGE] Nối TS-copy {len(paths)} file ({total_in:.0f}s → {out_dur:.0f}s) — không re-encode")
                _clean_list()
                return output_path
            logger.warning(f"[MERGE] TS-copy lệch thời lượng (vào {total_in:.1f}s, ra {out_dur:.1f}s) — fallback re-encode")
        except Exception as e:
            logger.warning(f"[MERGE] TS-copy thất bại ({e}) — fallback re-encode NVENC")
        finally:
            for ts in ts_files:
                try:
                    os.remove(ts)
                except Exception:
                    pass
    cmd = ['ffmpeg', '-y', '-threads', '0', '-f', 'concat', '-safe', '0', '-i', list_file,
           '-r', str(OUTPUT_FPS), '-fps_mode', 'cfr',
           ] + _nvenc_v_tail() + [
           '-c:a', 'aac', '-b:a', OUTPUT_AUDIO_BITRATE, '-ar', str(OUTPUT_AUDIO_RATE), '-ac', '2',
           output_path]
    run_ffmpeg(cmd)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        _clean_list()
        return output_path
    # Fallback: nếu NVENC concat thất bại, re-encode CPU (libx264) — VẪN ép CFR
    # timeline liền mạch (KHÔNG -c copy: copy concat để PTS base lệch → video dài sai).
    # crf 22 ≈ ngang chất lượng VBR CQ26 (nhẹ hơn crf 20 cũ ~30%).
    cmd_cpu = ['ffmpeg', '-y', '-threads', '0', '-f', 'concat', '-safe', '0', '-i', list_file,
               '-r', str(OUTPUT_FPS), '-fps_mode', 'cfr',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
               '-c:a', 'aac', '-b:a', OUTPUT_AUDIO_BITRATE, '-ar', str(OUTPUT_AUDIO_RATE), '-ac', '2',
               '-movflags', '+faststart', output_path]
    run_ffmpeg(cmd_cpu)
    _clean_list()
    return output_path


def create_srt(segments: list, output_path: str):
    from backend.utils.srt_parser import seconds_to_time_short
    cur = 0.0
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            if seg.tts_duration <= 0: continue
            st, et = seconds_to_time_short(cur), seconds_to_time_short(cur + seg.tts_duration)
            f.write(f'{i}\n{st} --> {et}\n{seg.narration}\n\n')
            cur += seg.tts_duration
    return output_path


# ════════════════════════════════════════════════════════════════════
#  SHOT-BASED SMART EDITOR
#
#  VIDEO → Shot Detection → Shot Cache → Script Timestamp Matching
#        → Shot Selection → Edit Plan → FFmpeg Render → Output
#
#  Phiên bản này chỉ dùng TEMPORAL/TIMESTAMP matching trên shot boundary
#  phát hiện bằng FFmpeg scene detection (KHÔNG AI vision). Tất cả quyết
#  định được chốt trong một Edit Plan trung gian trước khi render.
# ════════════════════════════════════════════════════════════════════

class Shot:
    """Một shot/cảnh liên tục trong video nguồn (giây)."""
    def __init__(self, index: int, start: float, end: float):
        self.index = index
        self.start = round(start, 3)
        self.end = round(end, 3)
        self.duration = round(max(0.0, self.end - self.start), 3)

    def to_dict(self):
        return {'index': self.index, 'start': self.start, 'end': self.end, 'duration': self.duration}

    @staticmethod
    def from_dict(d):
        return Shot(int(d['index']), float(d['start']), float(d['end']))

    def __repr__(self):
        return f"Shot#{self.index} {self.start}→{self.end}"


class EditClip:
    """Một mảnh clip được chọn từ video nguồn cho edit plan."""
    def __init__(self, source_start: float, source_end: float, max_source_end: float = None, reverse: bool = False):
        self.source_start = round(source_start, 3)
        self.source_end = round(max(source_start, source_end), 3)
        self.duration = round(self.source_end - self.source_start, 3)
        # Giới hạn nguồn tối đa có thể dùng cho clip này (đầu cuối của shot/cảnh gốc,
        # hoặc mốc kết thúc segment nếu fallback). Khi tăng tốc, source_end chỉ được mở
        # rộng tới max_source_end — KHÔNG vượt thời lượng cảnh gốc.
        self.max_source_end = round(float(max_source_end), 3) if max_source_end is not None else round(self.source_end, 3)
        # Reverse: phát clip theo chiều TỪ CUỐI VỀ ĐẦU (gán bởi _assign_reverse).
        self.reverse = bool(reverse)

    def to_dict(self):
        return {'source_start': self.source_start, 'source_end': self.source_end, 'duration': self.duration,
                'max_source_end': self.max_source_end, 'reverse': self.reverse}


class EditPlanItem:
    """Edit plan cho MỘT script segment."""
    def __init__(self, script_index, timestamp, text, voice_duration):
        self.script_index = script_index
        self.timestamp = timestamp
        self.text = text
        self.voice_duration = voice_duration
        self.clips = []
        self.target_duration = round(voice_duration, 3)
        self.fallback = False  # True khi không tìm được shot chính xác, dùng shot/segment legacy

    def add_clip(self, source_start, source_end, max_source_end=None, reverse: bool = False):
        self.clips.append(EditClip(source_start, source_end, max_source_end, reverse=reverse))

    @property
    def actual_duration(self):
        return round(sum(c.duration for c in self.clips), 3)

    def to_dict(self):
        return {
            'script_index': self.script_index,
            'timestamp': self.timestamp,
            'text': self.text,
            'voice_duration': self.voice_duration,
            'target_duration': self.target_duration,
            'actual_duration': self.actual_duration,
            'fallback': self.fallback,
            'clips': [c.to_dict() for c in self.clips],
        }


def _shot_cache_dir():
    """Thư mục cache shot — nằm trong data/cache/shot (không bị cleanup xoá)."""
    d = os.path.join(CACHE_DIR, 'shot')
    os.makedirs(d, exist_ok=True)
    return d


def _shot_cache_key(video_path: str) -> str:
    """Key cache gắn với video: path + size + mtime → source đổi thì cache cũ không tái dùng."""
    try:
        st = os.stat(video_path)
        raw = f"{os.path.abspath(video_path)}|{st.st_size}|{int(st.st_mtime)}|{_detector_signature()}"
    except OSError:
        raw = f"{os.path.abspath(video_path)}|{_detector_signature()}"
    return hashlib.md5(raw.encode('utf-8', errors='ignore')).hexdigest()[:16]


def _resolve_shot_detector() -> str:
    """Chọn backend phát hiện shot theo SHOT_DETECTOR; 'auto' ưu tiên PySceneDetect nếu import được."""
    mode = str(SHOT_DETECTOR or 'auto').strip().lower()
    if mode == 'ffmpeg':
        return 'ffmpeg'
    if mode == 'pyscenedetect':
        return 'pyscenedetect'
    try:
        import scenedetect  # noqa: F401
        return 'pyscenedetect'
    except Exception:
        return 'ffmpeg'


def _detector_signature() -> str:
    """Chuỗi nhận diện detector+tham số — nằm trong hash khoá cache để đổi config là tự invalidate."""
    if _resolve_shot_detector() == 'pyscenedetect':
        method = str(PYSCENE_METHOD or 'adaptive').strip().lower()
        fs = max(0, int(PYSCENE_FRAME_SKIP if PYSCENE_FRAME_SKIP is not None else 1))
        if method == 'content':
            return f'pyscene-content-{PYSCENE_CONTENT_THRESHOLD}-{PYSCENE_MIN_SCENE_LEN}-fs{fs}'
        return f'pyscene-adaptive-{PYSCENE_ADAPTIVE_THRESHOLD}-{PYSCENE_MIN_CONTENT_VAL}-{PYSCENE_MIN_SCENE_LEN}-fs{fs}'
    return f'ffmpeg-{SHOT_SCENE_THRESHOLD}'


def detect_shots(video_path: str, progress_callback=None) -> list:
    """Phát hiện shot boundary — decode video ĐÚNG 1 LẦN.

    Backend theo SHOT_DETECTOR (mặc định 'auto' → PySceneDetect nếu cài được):
    - PySceneDetect: histogram HSV (bắt cut cảnh tối chuẩn hơn scene-score luma-only
      của ffmpeg) + bộ lọc flash-cut built-in.
    - FFmpeg: `select='gt(scene,THRESH)',showinfo` — parse `pts_time` từ stderr.
    Mỗi boundary là điểm BẮT ĐẦU một shot mới; KẾT THÚC shot trước đúng tại đó.
    Shot ≤ SHOT_MERGE_MIN (giây) bị gộp vào shot trước. Luôn trả về >= 1 shot.
    """
    detector = _resolve_shot_detector()
    label = 'PySceneDetect' if detector == 'pyscenedetect' else 'FFmpeg scene detection'
    if progress_callback:
        progress_callback(f'Phát hiện shot/cảnh bằng {label}...', 55)
    ctx = _FFMPEG_CANCEL_CTX.get()
    if ctx and ctx['is_cancelled']():
        _cancelled_error()
    try:
        if detector == 'pyscenedetect':
            shots = _detect_shots_pyscene(video_path)
        else:
            shots = _detect_shots_ffmpeg(video_path)
    except Exception as e:
        if str(e).startswith('__CANCELLED__') or (ctx and ctx['is_cancelled']()):
            raise  # hủy giữa chừng → không fallback, dừng luôn
        if detector != 'ffmpeg':
            logger.exception("[SHOT] PySceneDetect lỗi, fallback FFmpeg")
            shots = _detect_shots_ffmpeg(video_path)
        else:
            raise
    filtered = _filter_micro_shots(shots)
    return filtered or shots


def _detect_shots_ffmpeg(video_path: str) -> list:
    """Backend FFmpeg: scene-score threshold cố định. Trả về shot thô (chưa gộp micro-shot)."""
    ctx = _FFMPEG_CANCEL_CTX.get()
    vf = f"select='gt(scene,{SHOT_SCENE_THRESHOLD})',showinfo"
    cmd = ['ffmpeg', '-nostats', '-i', video_path,
           '-vf', vf, '-an', '-f', 'null', '-']
    # Quét scene chỉ decode CPU + xuất null (không encode/GPU) → không giữ lock phần cứng,
    # để TTS probe + episode khác encode không bị block suốt lần quét dài nhất pipeline.
    try:
        res = _cancellable_run(cmd, timeout=600)
    except subprocess.TimeoutExpired:
        res = None
        logger.warning("[SHOT] scene detection timeout, dùng 1 shot toàn phần")
    except Exception as e:
        if str(e).startswith('__CANCELLED__') or (ctx and ctx['is_cancelled']()):
            raise
        res = None
        logger.warning("[SHOT] scene detection lỗi, dùng 1 shot toàn phần: %s", e)

    boundaries = []
    if res is not None:
        for line in (res.stderr or '').splitlines():
            if 'pts_time:' not in line:
                continue
            m = None
            for tok in line.split():
                if tok.startswith('pts_time:'):
                    m = tok.split(':', 1)[1]
                    break
            if m is None:
                continue
            try:
                t = float(m)
            except ValueError:
                continue
            if t > 0.02:  # bỏ boundary tại 0 (đầu video)
                boundaries.append(t)

    duration = 0.0
    try:
        duration = get_real_video_duration(video_path)
    except Exception:
        pass

    boundaries = sorted(set(round(b, 3) for b in boundaries))
    shots = []
    prev = 0.0
    idx = 1
    for b in boundaries + ([duration] if duration > 0 else []):
        if b - prev >= 0.2:
            shots.append(Shot(idx, prev, b))
            idx += 1
        prev = max(prev, b)
    if not shots:
        shots.append(Shot(1, 0.0, duration if duration > 0 else 10.0))
    return shots


def _detect_shots_pyscene(video_path: str) -> list:
    """Backend PySceneDetect: ContentDetector (threshold cố định + built-in flash merge)
    hoặc AdaptiveDetector (ngưỡng thích ứng cục bộ, bền với đoạn chuyển cảnh dày).
    Đã tối ưu tốc độ tối đa:
    - Ưu tiên backend pyav (decode C đa luồng nhanh hơn OpenCV).
    - frame_skip (mặc định 1: giảm 50% tính toán, nhanh gấp đôi, lệch <= 0.04s).
    - Tự động dùng video nén 480p proxy nếu có trong output/manual/ (nhanh hơn 3-4x).
    """
    import scenedetect
    from scenedetect import SceneManager, open_video, FrameTimecode
    from scenedetect.detectors import ContentDetector, AdaptiveDetector

    scan_path = video_path
    if PYSCENE_USE_PROXY:
        try:
            base2 = os.path.splitext(os.path.basename(video_path))[0]
            base2 = re.sub(r'^\d+_', '', base2)
            candidate = os.path.join(MANUAL_DIR, f'{base2}_manual_sm.mp4')
            if os.path.exists(candidate) and os.path.getsize(candidate) > 10000:
                scan_path = candidate
                logger.info(f"[SHOT] PySceneDetect dùng proxy video nén: {os.path.basename(candidate)}")
            elif os.path.isdir(MANUAL_DIR):
                for fn in os.listdir(MANUAL_DIR):
                    if base2 in fn and fn.endswith('.mp4') and os.path.getsize(os.path.join(MANUAL_DIR, fn)) > 10000:
                        scan_path = os.path.join(MANUAL_DIR, fn)
                        logger.info(f"[SHOT] PySceneDetect dùng proxy video nén: {fn}")
                        break
        except Exception as e:
            logger.debug(f"[SHOT] Không tìm thấy proxy video: {e}")

    method = str(PYSCENE_METHOD or 'adaptive').strip().lower()
    min_len = f"{max(0.1, float(PYSCENE_MIN_SCENE_LEN)):.3f}s"
    detector = None
    if method == 'content':
        detector = ContentDetector(
            threshold=max(5.0, PYSCENE_CONTENT_THRESHOLD),
            min_scene_len=min_len,
        )
    else:
        detector = AdaptiveDetector(
            adaptive_threshold=max(0.1, PYSCENE_ADAPTIVE_THRESHOLD),
            min_content_val=max(1.0, PYSCENE_MIN_CONTENT_VAL),
            min_scene_len=min_len,
        )

    avail_backends = getattr(scenedetect.backends, 'AVAILABLE_BACKENDS', {})
    req_backend = str(PYSCENE_BACKEND or 'auto').strip().lower()
    if req_backend == 'pyav' and 'pyav' in avail_backends:
        backend_choice = 'pyav'
    elif req_backend == 'opencv':
        backend_choice = 'opencv'
    else:
        backend_choice = 'pyav' if 'pyav' in avail_backends else 'opencv'

    frame_skip = max(0, int(PYSCENE_FRAME_SKIP if PYSCENE_FRAME_SKIP is not None else 1))
    logger.info(f"[SHOT] PySceneDetect quét: backend={backend_choice}, method={method}, frame_skip={frame_skip}")

    video = None
    scene_list = []
    # PySceneDetect decode CPU thuần trong process Python (không đụng GPU/ffmpeg) →
    # không giữ LOCAL_HARDWARE_LOCK để episode khác encode/probe song song.
    try:
        video = open_video(scan_path, backend=backend_choice)
        sm = SceneManager()
        sm.add_detector(detector)
        sm.detect_scenes(video=video, frame_skip=frame_skip, show_progress=False)
        scene_list = sm.get_scene_list()
    finally:
        if video is not None:
            try:
                if hasattr(video, 'capture') and video.capture is not None:
                    video.capture.release()
                if hasattr(video, '_container') and video._container is not None:
                    video._container.close()
                if hasattr(video, '_io') and hasattr(video._io, 'close'):
                    video._io.close()
            except Exception:
                pass

    duration = 0.0
    try:
        duration = get_real_video_duration(video_path)
    except Exception:
        pass
    if scene_list:
        last_end = scene_list[-1][1].get_seconds()
        if duration > 0:
            last_end = max(last_end, duration)

    shots = []
    idx = 1
    for start, end in scene_list:
        s = start.get_seconds()
        e = end.get_seconds()
        if e - s >= 0.1:
            shots.append(Shot(idx, round(s, 3), round(e, 3)))
            idx += 1
    if not shots:
        shots.append(Shot(1, 0.0, duration if duration > 0 else 10.0))
    return shots



def _filter_micro_shots(shots: list) -> list:
    """Gộp shot ≤ SHOT_MERGE_MIN (giây) vào shot TRƯỚC nó (dọn micro-shot/flash nhận nhầm)."""
    merge_min = max(0.1, float(SHOT_MERGE_MIN))
    filtered = []
    for s in shots:
        if filtered and s.duration < merge_min:
            filtered[-1].end = s.end
            filtered[-1].duration = round(filtered[-1].end - filtered[-1].start, 3)
        else:
            filtered.append(s)
    for i, s in enumerate(filtered, 1):
        s.index = i
    return filtered


def _load_shot_cache(video_path: str):
    key = _shot_cache_key(video_path)
    path = os.path.join(_shot_cache_dir(), f'{key}.shots.json')
    if not os.path.exists(path):
        return None, key
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        shots = [Shot.from_dict(s) for s in data.get('shots', [])]
        if not shots:
            return None, key
        logger.info(f"[SHOT] dùng cache {len(shots)} shots từ {path}")
        return shots, key
    except Exception:
        return None, key


def _save_shot_cache(video_path: str, key: str, shots: list):
    path = os.path.join(_shot_cache_dir(), f'{key}.shots.json')
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'shots': [s.to_dict() for s in shots]}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"[SHOT] không ghi cache {path}: {e}")


def get_shots(video_path: str, progress_callback=None) -> list:
    """Trả shot index, đọc cache nếu có; ngược lại chạy detection 1 lần và cache lại."""
    cached, key = _load_shot_cache(video_path)
    if cached is not None:
        return cached
    shots = detect_shots(video_path, progress_callback)
    _save_shot_cache(video_path, key, shots)
    logger.info(f"[SHOT] Detected {len(shots)} shots")
    return shots


def _shots_in_window(shots: list, ts: float, before: float, after: float):
    """Các shot giao với [ts-before, ts+after]."""
    lo, hi = ts - before, ts + after
    out = []
    for s in shots:
        if s.end > lo and s.start < hi:
            out.append(s)
    return out


def _inside_skipped(s: Shot) -> bool:
    """True nếu shot nằm hoàn toàn trong vùng intro/outro bị bỏ qua."""
    if not SKIP_INTRO_OUTRO:
        return False
    if INTRO_SKIP_SECONDS and s.end <= INTRO_SKIP_SECONDS:
        return True
    return False


def _pending_skipped(shots) -> float:
    """Thời điểm hết vùng intro cần bỏ qua (đầu video)."""
    return INTRO_SKIP_SECONDS if (SKIP_INTRO_OUTRO and INTRO_SKIP_SECONDS) else 0.0


def build_edit_plan(segments: list, shots: list, video_duration: float) -> list:
    """Sinh edit plan cho từng script segment.

    Với mỗi segment: mốc trung tâm = segment.start_seconds, tìm shot trong cửa sổ
    [ts-WINDOW_BEFORE, ts+WINDOW_AFTER]. Chọn chuỗi shot sao cho tổng ≈ segment.tts_duration
    (±VOICE_SYNC_TOLERANCE), ưu tiên shot chứa timestamp, tránh shot đã dùng gần (used_shots),
    tôn trọng MIN/MAX_CLIP_DURATION. KHÔNG cắt máy móc 10-30s; nếu không tìm được → fallback
    về clip temporal từ timestamp script (giữ theo phạm vi segment gốc).
    """
    plan = []
    used = []  # (start,end) các đoạn video ĐÃ cắt, để tránh lặp lại cùng pixel

    def _find_used_overlap(seg_start, seg_end):
        # Trả về điểm kết thúc muộn nhất mà đoạn định lấy chồng lấn với 1 clip đã dùng
        # (để greedy có thể dịch sang phần chưa dùng của shot). Nếu không overlap → None.
        overlap_end = None
        for (u0, u1) in used:
            if u0 < seg_end and seg_start < u1:
                overlap_end = u1 if overlap_end is None else max(overlap_end, u1)
        return overlap_end

    for seg in segments:
        ts = float(getattr(seg, 'start_seconds', 0) or 0)
        vdur = float(getattr(seg, 'tts_duration', 0) or 0)
        item = EditPlanItem(getattr(seg, 'index', 0), ts,
                            getattr(seg, 'narration', '') or '', vdur)
        target = vdur if vdur > 0 else 1.5

        # Bỏ vùng intro nếu bật
        lo = max(_pending_skipped(shots), ts - SEARCH_WINDOW_BEFORE)
        hi = ts + SEARCH_WINDOW_AFTER
        # Tất cả shot trong window là ứng viên; ưu tiên shot CHỨA timestamp lên đầu,
        # còn lại sắp theo độ gần timestamp.
        candidates = [s for s in shots if s.end > lo + 0.01 and s.start < hi]
        if not candidates:
            candidates = [s for s in shots if s.end > lo and s.start < hi + SEARCH_WINDOW_AFTER * 2]
        containing = [s for s in candidates if s.start <= ts <= s.end]
        def _key(s):
            dist = abs((s.start + s.end) / 2 - ts)
            # ưu tiên shot CHỨA ts trước; trong đó ưu tiên shot mà ts KHÔNG nằm sát ranh giới đầu
            edge_penalty = 1 if (s in containing and ts - s.start < 0.5) else 0
            return (0 if s in containing else 1, edge_penalty, dist, s.start)
        pool = sorted(candidates, key=_key)

        # Không lọc pool theo reuse ở đây: việc chống lặp xử lý trong greedy bằng cách
        # dịch sang phần chưa dùng của shot (chỉ bỏ shot nếu KHÔNG CÒN phần nào dùng được).

        if pool:
            # Greedy: nhặt shot LIÊN TIẾP theo thứ tự ưu tiên. Nếu phần đầu shot đã được
            # cắt cho segment trước, dịch sang phần chưa dùng để tránh lặp lại cảnh.
            remaining = target
            for s in pool:
                if remaining <= 0:
                    break
                if s.duration < MIN_CLIP_DURATION - 0.2:
                    continue
                if s.duration <= remaining + VOICE_SYNC_TOLERANCE:
                    # shot ngắn hơn nhu cầu còn lại → nhặt TRỌN shot (giữ boundary)
                    take = s.duration
                else:
                    # shot đủ lớn → chỉ lấy phần cần để về đích (±tolerance)
                    take = max(MIN_CLIP_DURATION, remaining + VOICE_SYNC_TOLERANCE)
                # Lấy phần GIỮA shot: bỏ đầu/đuôi đều nhau (margin mỗi bên = (dur-take)/2)
                if s.duration > take + 0.2:
                    margin = (s.duration - take) / 2.0
                    seg_start = s.start + margin
                else:
                    seg_start = s.start
                seg_end = min(s.end, seg_start + take)
                # Nếu phần này đã bị dùng, dịch sang phần CHƯA dùng của shot
                overlap_end = _find_used_overlap(seg_start, seg_end)
                if overlap_end is not None:
                    seg_start = max(seg_start, overlap_end)
                    seg_end = min(s.end, seg_start + take)
                    if seg_end - seg_start < MIN_CLIP_DURATION - 0.2:
                        continue  # shot không còn đủ phần mới để dùng → bỏ
                item.add_clip(seg_start, seg_end, s.end)
                used.append((seg_start, seg_end))
                remaining -= (seg_end - seg_start)

        # 2. Fallback: clip temporal theo phạm vi segment gốc, NHƯNG clamp vào phần video thực.
        #    Nếu mốc script vượt data thực (video cụt): QUẤN mốc về trong [0, fallback_sec)
        #    thay vì dồn toàn bộ về 1 giây cuối (tránh lặp y hệt cùng khung hình nhiều lần),
        #    rồi né phần đã dùng giống nhánh greedy để mỗi segment lấy cảnh khác nhau.
        fallback_sec = max(0.0, video_duration if video_duration > 0 else 0.0)
        min_dur = max(MIN_CLIP_DURATION, 1.0)
        if not item.clips and fallback_sec > 0:
            st = float(getattr(seg, 'start_seconds', 0) or 0)
            et = float(getattr(seg, 'end_seconds', st + target) or (st + target))
            if st >= fallback_sec:
                # Mốc kịch bản ngoài video thực → quấn vào lòng video.
                st = (st % fallback_sec) if fallback_sec > min_dur else 0.0
            pending = _pending_skipped(shots)
            st = max(pending, st)
            if et <= st or et > fallback_sec:
                et = min(fallback_sec, st + max(target, min_dur))
            if et <= st:
                st = max(pending, fallback_sec - min_dur)
                et = min(fallback_sec, st + min_dur)
            if et - st < min_dur:
                et = min(fallback_sec, st + min_dur)
            if et - st >= 0.5:
                take = et - st
                overlap_end = _find_used_overlap(st, et)
                if overlap_end is not None:
                    st = max(st, overlap_end)
                    et = min(fallback_sec, st + take)
                    if et - st < min_dur - 0.2:
                        st = max(pending, fallback_sec - min_dur)
                        et = min(fallback_sec, st + min_dur)
                item.fallback = True
                logger.info(f"[MATCH] No suitable shot found @ {ts:.1f}s → [FALLBACK] clip "
                            f"[{_fmt_ts(st)} → {_fmt_ts(et)}] trong video thực {fallback_sec:.1f}s")
                item.add_clip(st, et, et)
                used.append((st, et))

        for c in item.clips:
            logger.info(f"[MATCH] Script #{item.script_index} @ {_fmt_ts(ts)} "
                        f"Selected: {_fmt_ts(c.source_start)} → {_fmt_ts(c.source_end)}")
        logger.info(f"[EDIT] Target duration: {item.target_duration:.2f}s, "
                    f"Actual: {item.actual_duration:.2f}s")
        plan.append(item)

    return plan


def _assign_reverse(plan: list) -> None:
    """Gán cờ reverse cho clip TRONG TỪNG CẢNH (edit plan item) — mỗi cảnh nhiều shot.

    Quy tắc (chỉ áp cho reverse): số shot reverse của MỘT CẢNH nằm trong [1/3, 1/2]
    số shot của cảnh đó (M ≤ 1 → không reverse); không có chuỗi quá 2 shot reverse
    liền kề; ưu tiên shot ngắn (duration <= SHOT_REVERSE_MAX_SEC), thiếu thì lấp bằng
    shot dài hơn cho đủ tỷ lệ. Greedy + pass 2 điền bù luôn khả thi (run ≤ 2).
    """

    def _pick(item) -> None:
        clips = item.clips
        m = len(clips)
        if m <= 1:
            for c in clips:
                c.reverse = False
            return
        k_lo = -(-m // 3)          # ceil(m/3)
        k_hi = m // 2              # floor(m/2)
        if k_lo > k_hi:
            for c in clips:
                c.reverse = False
            return
        k_rev = random.randint(k_lo, k_hi)
        short = [i for i, c in enumerate(clips) if c.duration <= SHOT_REVERSE_MAX_SEC]
        long_ = [i for i, c in enumerate(clips) if c.duration > SHOT_REVERSE_MAX_SEC]
        random.shuffle(short)
        random.shuffle(long_)
        order = short + long_
        chosen = [False] * m

        def _run_three(i: int) -> bool:
            if i >= 2 and chosen[i - 2] and chosen[i - 1]:
                return True
            if i >= 1 and i + 1 < m and chosen[i - 1] and chosen[i + 1]:
                return True
            if i + 2 < m and chosen[i + 1] and chosen[i + 2]:
                return True
            return False

        cnt = 0
        for i in order:
            if cnt >= k_rev:
                break
            if not chosen[i] and not _run_three(i):
                chosen[i] = True
                cnt += 1
        # Pass 2: điền bù các vị trí hợp lệ còn lại (không tạo chuỗi 3) cho đủ k_rev.
        if cnt < k_rev:
            for i in range(m):
                if cnt >= k_rev:
                    break
                if chosen[i] or _run_three(i):
                    continue
                chosen[i] = True
                cnt += 1
        for c, flag in zip(clips, chosen):
            c.reverse = bool(flag)

    for item in plan:
        _pick(item)


def _fmt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def _fx_opts(opts, key, default: bool) -> bool:
    """Đọc cờ hiệu ứng từ per-task/project options; thiếu thì dùng global env default."""
    if opts is None:
        return bool(default)
    val = opts.get(key)
    if val is None or val == '':
        return bool(default)
    return str(val) not in ('0', 'false', 'False', 'off', 'no')


def render_smart_shot(video_path: str, segments: list, edit_mode='smart_shot',
                      progress_callback=None, work_dir=None, opts=None,
                      is_cancelled=None, register=None, unregister=None) -> list:
    """Render theo edit plan shot-based. Trả về danh sách file merged clip đã ghép audio.

    Kiến trúc: detect/cache shots → build_edit_plan → cắt từng clip (cut_and_fit_segment,
    tái sử dụng) → ghép audio (merge_one) → trả merged clips để pipeline concat tiếp.
    opts có thể mang 4 cờ hiệu ứng độc lập fx_flip/fx_zoom/fx_speed/fx_reverse ('1'/'0').
    """
    if edit_mode != 'smart_shot':
        return cut_merge_all_segments(video_path, segments, progress_callback, work_dir,
                                      is_cancelled=is_cancelled, register=register, unregister=unregister)

    shots = get_shots(video_path, progress_callback)
    total_s = len(shots)
    logger.info(f"[SHOT] Detected/loaded {total_s} shots")
    if progress_callback:
        progress_callback(f'Phát hiện {total_s} shot. Dựng edit plan...', 62)

    video_duration = 0.0
    try:
        video_duration = get_real_video_duration(video_path)
    except Exception:
        pass

    plan = build_edit_plan(segments, shots, video_duration)
    if _fx_opts(opts, 'fx_reverse', SMART_SHOT_REVERSE):
        _assign_reverse(plan)
    # Cờ hiệu ứng cho từng segment: lấy tại thời điểm chạy từng segment.
    fx_flip = _fx_opts(opts, 'fx_flip', SMART_SHOT_ALTERNATE_FLIP)
    fx_zoom = _fx_opts(opts, 'fx_zoom', SMART_SHOT_ZOOM_PERCENT > 100)
    fx_speed = _fx_opts(opts, 'fx_speed', SMART_SHOT_SPEED_MAX > 1.0)
    # Lưu edit plan để debug/preview
    try:
        _save_edit_plan(video_path, plan)
    except Exception:
        pass

    import threading
    concurrency = _render_concurrency()
    threads = _threads_for(concurrency)
    plan_work = [(i, item) for i, item in enumerate(plan, 1) if item.clips and (i - 1) < len(segments)]
    merged = [None] * len(plan_work)
    done_lock = threading.Lock()
    done_count = 0

    def do_one(idx):
        nonlocal done_count
        i, item = plan_work[idx]
        seg = segments[i - 1]
        # Lật gương ngang SO LE từng segment (chẵn lật, lẻ nguyên) — nhịp đảo cảnh liên tục.
        # (chỉ khi checkbox fx_flip được chọn)
        flip = fx_flip and (i % 2 == 0)
        # Zoom 125% vào 1 vị trí NGẪU NHIÊN cho RIÊNG segment này (lệnh crop cố định → không rung).
        zoom_center = None
        if fx_zoom and SMART_SHOT_ZOOM_PERCENT > 100:
            w, h = OUTPUT_RESOLUTION
            z = SMART_SHOT_ZOOM_PERCENT / 100.0
            cw = int(w / z); cw -= cw % 2
            ch = int(h / z); ch -= ch % 2
            if cw > 0 and ch > 0:
                zoom_center = (random.randint(0, max(0, w - cw)),
                               random.randint(0, max(0, h - ch)))
        # Tăng tốc NGẪU NHIÊN (S) cho từng cảnh, giữ tổng thời lượng = lời bình:
        #  - chọn S ngẫu nhiên trong [SMART_SHOT_SPEED_MIN, MAX];
        #  - nguồn cần cho cảnh ≈ S × target_duration → mở rộng từng clip theo tỷ lệ w sao
        #    cho tổng nguồn mới đạt con số đó (clamp bằng max_source_end của shot/segment);
        #  - nếu nguồn thực tế không đủ (cảnh gốc ngắn) → rút S xuống (không vượt cảnh gốc);
        #  - cắt với setpts=1/S → output vẫn ≈ lời bình, nhưng chuyển động nhanh hơn S lần.
        speed = 1.0
        if fx_speed and SMART_SHOT_SPEED_MAX > 1.0 and item.target_duration > 0:
            s_lo = max(1.0, min(SMART_SHOT_SPEED_MIN, SMART_SHOT_SPEED_MAX))
            s_hi = max(s_lo, SMART_SHOT_SPEED_MAX)
            speed = random.uniform(s_lo, s_hi)
            pool_src = sum(max(0.0, c.max_source_end - c.source_start) for c in item.clips)
            if pool_src > 0:
                speed = min(speed, max(1.0, pool_src / item.target_duration))
            if speed > 1.001:
                total_cur = sum(c.duration for c in item.clips) or 1.0
                w = speed * item.target_duration / total_cur
                for c in item.clips:
                    new_end = min(c.max_source_end, c.source_start + c.duration * w)
                    c.source_end = round(new_end, 3)
                    c.duration = round(max(0.05, c.source_end - c.source_start), 3)
                # tốc độ thực theo nguồn đã mở rộng (có thể < S nếu clip bị clamp mạnh)
                total_new = sum(c.duration for c in item.clips) or item.target_duration
                speed = max(1.0, min(speed, total_new / item.target_duration))
        # cắt từng clip theo plan
        seg_out = os.path.join(work_dir or SEGMENTS_DIR, f'seg_{i:03d}.mp4')
        _cut_plan_clips(video_path, item, seg_out, threads, lock=False, flip=flip, zoom_center=zoom_center, speed=speed)
        seg.video_segment_path = seg_out
        seg.shot_count = len(item.clips)  # số shot dùng cho cảnh này — hiển thị trong xem kịch bản
        seg_out_merged = _merge_one(seg, threads, work_dir, lock=False)
        with done_lock:
            done_count += 1
            cur = done_count
        if progress_callback:
            progress_callback(f'Dựng đoạn theo shot [{cur}/{len(plan)}]', 64 + int((cur / len(plan)) * 30))
        return seg_out_merged

    with ThreadPoolExecutor(max_workers=concurrency, initializer=_pool_session_init,
                            initargs=(is_cancelled, register, unregister)) as ex:
        results = list(ex.map(do_one, range(len(plan_work))))
    return [m for m in results if m]


def _cut_reverse_chunked(video_path: str, c, output_path: str, threads: str, lock: bool = True, flip: bool = False, zoom_center: tuple = None, speed: float = 1.0):
    """Cắt 1 clip reverse, chia thành các cửa sổ nối tiếp ≤ REVERSE_CHUNK_SEC (mỗi cửa
    sổ reverse độc lập) rồi ghép lại. Filter `reverse` buffer TOÀN BỘ clip trong RAM
    (1080p30 ≈ 93MB/giây) — clip dài không chia sẽ phình RAM hàng GB rồi tràn sang
    pagefile gây disk 100%. Clip ≤ ngưỡng giữ nguyên reverse liền mạch một lần."""
    chunk = max(2.0, float(REVERSE_CHUNK_SEC))
    total = max(0.5, c.source_end - c.source_start)
    if total <= chunk:
        cut_and_fit_segment(video_path, c.source_start, c.source_end,
                            total, output_path, threads, lock=lock, flip=flip,
                            zoom_center=zoom_center, speed=speed, reverse=True)
        return
    base = os.path.dirname(output_path) or '.'
    stem = os.path.basename(output_path)
    parts = []
    try:
        ws = c.source_start
        k = 0
        while ws < c.source_end - 0.2:
            we = min(c.source_end, ws + chunk)
            tmp = os.path.join(base, f'{stem}.rev{k}.mp4')
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            cut_and_fit_segment(video_path, ws, we, we - ws, tmp, threads, lock=lock,
                                flip=flip, zoom_center=zoom_center, speed=speed, reverse=True)
            parts.append(tmp)
            ws = we
            k += 1
        if not parts:
            raise RuntimeError('Không chia được clip reverse thành cửa sổ')
        logger.info(f"[REVERSE] Clip {total:.1f}s → {len(parts)} cửa sổ ≤{chunk:.0f}s (giới hạn RAM)")
        _concat_clips(parts, output_path, lock=lock)
    finally:
        for t in parts:
            try:
                if os.path.exists(t):
                    os.remove(t)
            except Exception:
                pass


def _cut_plan_clips(video_path: str, item: EditPlanItem, output_path: str, threads: str, lock: bool = True, flip: bool = False, zoom_center: tuple = None, speed: float = 1.0):
    """Cắt các clip trong item rồi nối thành 1 file segment (h264_nvenc/yuv420p) → sẵn cho merge audio."""
    if len(item.clips) == 1:
        c = item.clips[0]
        if c.reverse:
            _cut_reverse_chunked(video_path, c, output_path, threads, lock=lock, flip=flip, zoom_center=zoom_center, speed=speed)
        else:
            cut_and_fit_segment(video_path, c.source_start, c.source_end,
                                c.duration, output_path, threads, lock=lock, flip=flip, zoom_center=zoom_center, speed=speed)
        return
    parts = []
    base = os.path.dirname(output_path) or '.'
    stem = os.path.basename(output_path)
    try:
        for ci, c in enumerate(item.clips):
            tmp = os.path.join(base, f'{stem}.shot{ci}.mp4')
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            if c.reverse:
                _cut_reverse_chunked(video_path, c, tmp, threads, lock=lock, flip=flip, zoom_center=zoom_center, speed=speed)
            else:
                cut_and_fit_segment(video_path, c.source_start, c.source_end,
                                    c.duration, tmp, threads, lock=lock, flip=flip, zoom_center=zoom_center, speed=speed)
            parts.append(tmp)
        if not all(os.path.exists(t) and os.path.getsize(t) > 0 for t in parts):
            raise RuntimeError('Một clip cắt bị rỗng')
        # Đảo shot theo cặp liền kề (không ngẫu nhiên): (1,2)→(2,1), (3,4)→(4,3),...
        # Shot lẻ còn sót lại ở cuối giữ nguyên. Chỉ xáo trộn clip đã cắt (parts), nguồn không đổi.
        if SMART_SHOT_SHUFFLE and len(parts) >= 2:
            before = list(parts)
            for i in range(0, len(parts) - 1, 2):
                parts[i], parts[i + 1] = parts[i + 1], parts[i]
            swapped = sum(1 for a, b in zip(before, parts) if a != b)
            getno = lambda p: int(os.path.basename(p).rsplit('.', 1)[0].split('shot')[-1])
            logger.info(f"[SHUFFLE] Seg#{item.script_index}: {len(parts)} shots → đổi cặp {swapped}/{len(parts)}"
                        f" thứ tự {[getno(p) for p in before]} → {[getno(p) for p in parts]}")
        _concat_clips(parts, output_path, lock=lock)
    finally:
        for t in parts:
            try:
                if os.path.exists(t):
                    os.remove(t)
            except Exception:
                pass


def _save_edit_plan(video_path: str, plan: list):
    key = _shot_cache_key(video_path)
    path = os.path.join(_shot_cache_dir(), f'{key}.editplan.json')
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'plan': [it.to_dict() for it in plan]}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"[EDIT] không ghi edit plan {path}: {e}")

