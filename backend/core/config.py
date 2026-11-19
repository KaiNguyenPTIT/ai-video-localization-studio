import os
import threading
from dotenv import load_dotenv

load_dotenv()

# Khóa TOÀN CỤC cho mọi tiến trình dùng phần cứng máy (FFmpeg/ffprobe nén, cắt, ghép).
# RLock: nhiều worker chạy song song (mỗi épisode) nhưng phần cứng vẫn TUẦN TỰ —
# chỉ các bước gửi API/backend (Gemini upload, CapCut TTS) được chạy đồng thời.
LOCAL_HARDWARE_LOCK = threading.RLock()

# Khóa upload video lên Gemini: bước truyền file qua mạng tốn băng thông nhất —
# chạy TỪNG VIDEO MỘT để tránh nghẽn mạng khi nhiều tập chạy song song.
# Các bước API khác (CapCut TTS, generate_content) KHÔNG bị khóa, vẫn song song.
GEMINI_UPLOAD_LOCK = threading.RLock()

# ── Quản lý song song theo TỪNG LOẠI NGUỒN LỰC (tách khỏi "số tập đang chạy") ──
# Trước đây: số worker = số tập = cứng 2, nên khi 2 tập cùng dừng ở Gemini/TTS (mạng)
# thì CPU/đĩa RẢNH nhưng các tập queue vẫn phải đợi hết slots.
# Nay: số tập vào nền nhiều hơn (MAX_INFLIGHT_EPISODES) nhưng MỖI BƯỚC tự siết:
#   + Bước MẠNG (Gemini summarize, CapCut TTS): tối đa MAX_NETWORK_EPISODES tập
#     qua NETWORK_EPISODE_LOCK (BoundedSemaphore).
#   + Bước PHẦN CỨNG (FFmpeg/ffprobe): tuần tự toàn cục qua LOCAL_HARDWARE_LOCK (tối đa 1).
# => Không bước nào vượt quá 2 tập cùng lúc, nhưng bước đang rảnh (vd nén video CPU)
#    luôn có việc làm từ các tập khác thay vì ngồi chờ slot.
MAX_NETWORK_EPISODES  = 2
MAX_INFLIGHT_EPISODES = 6
NETWORK_EPISODE_LOCK  = threading.BoundedSemaphore(MAX_NETWORK_EPISODES)

# Giới hạn số TẬP được chạy ĐỒNG THỜI trong pipeline: mọi bước (nén, upload Gemini,
# TTS, cắt/ghép...) chỉ được tối đa 2 tập cùng chạy một lúc để không nghẽn mạng/CPU.
MAX_PARALLEL_EPISODES = 2

# ── Smart Shot-Based Editor ───────────────────────────────────
# Chế độ dựng mặc định: 'smart_shot' (phát hiện shot + khớp timestamp script +
# sinh edit plan + 4 hiệu ứng) hoặc 'legacy' (giữ nguyên hành vi chia đôi/đảo cảnh cũ).
EDIT_MODE_DEFAULT = os.getenv('EDIT_MODE_DEFAULT', 'smart_shot')

# Shot detection: ngưỡng scene score của FFmpeg (0..1, càng thấp càng nhạy → nhiều shot).
SHOT_SCENE_THRESHOLD = float(os.getenv('SHOT_SCENE_THRESHOLD', '0.2'))

# Backend phát hiện shot: 'auto' (ưu tiên PySceneDetect nếu import được, fallback FFmpeg),
# 'pyscenedetect' | 'ffmpeg'. PySceneDetect dùng metric histogram HSV (bắt cut cảnh tối chuẩn
# hơn nhiều so với scene-score luma-only của FFmpeg) + bộ lọc flash-cut built-in.
SHOT_DETECTOR = os.getenv('SHOT_DETECTOR', 'auto')

# PySceneDetect: 'adaptive' (AdaptiveDetector — ngưỡng thích ứng cục bộ, chống vỡ cảnh ở
# đoạn chuyển cảnh dày) hoặc 'content' (ContentDetector — ngưỡng cố định, kèm merge flash).
PYSCENE_METHOD = os.getenv('PYSCENE_METHOD', 'adaptive')
PYSCENE_ADAPTIVE_THRESHOLD = float(os.getenv('PYSCENE_ADAPTIVE_THRESHOLD', '3.0'))
PYSCENE_MIN_CONTENT_VAL     = float(os.getenv('PYSCENE_MIN_CONTENT_VAL', '15.0'))
PYSCENE_CONTENT_THRESHOLD   = float(os.getenv('PYSCENE_CONTENT_THRESHOLD', '27.0'))
# Shot ngắn nhất được giữ làm shot riêng (giây) ở cả 2 detector của PySceneDetect.
PYSCENE_MIN_SCENE_LEN = float(os.getenv('PYSCENE_MIN_SCENE_LEN', '0.4'))
# Tối ưu tốc độ PySceneDetect:
# frame_skip: số frame bỏ qua (1 = quét 12fps thay vì 24fps, nhanh gấp đôi, lệch <= 0.04s)
PYSCENE_FRAME_SKIP = int(os.getenv('PYSCENE_FRAME_SKIP', '2'))
# Backend decode: 'auto' (ưu tiên pyav đa luồng C nếu có, fallback opencv), 'pyav', 'opencv'
PYSCENE_BACKEND = os.getenv('PYSCENE_BACKEND', 'auto')
# Tự động ưu tiên quét trên bản nén 480p có sẵn (nhanh gấp 3-4x mà timeline khớp 100%)
PYSCENE_USE_PROXY = os.getenv('PYSCENE_USE_PROXY', '1') not in ('0', 'false', 'False')

# Chế độ tên nhân vật trong lời bình: 'vietnamese' (dùng tên dịch tiếng Việt) hoặc
# 'romaji' (giữ nguyên tên gốc Latin hóa). Điều chỉnh prompt để AI chỉ xuất 1 ngôn ngữ.
CHARACTER_NAME_MODE = os.getenv('CHARACTER_NAME_MODE', 'romaji')
# Post-filter CHUNG cho mọi backend: shot ≤ SHOT_MERGE_MIN (giây) bị gộp vào shot trước nó
# (dọn micro-shot/flash bị nhận nhầm thành cut riêng).
SHOT_MERGE_MIN = float(os.getenv('SHOT_MERGE_MIN', '0.5'))
# Giới hạn duration mỗi shot được CHỌN làm clip (shot ngắn hơn/dài hơn vẫn là boundary hợp lệ).
SHOT_MIN_DURATION = float(os.getenv('SHOT_MIN_DURATION', '0.8'))
SHOT_MAX_DURATION = float(os.getenv('SHOT_MAX_DURATION', '8.0'))

# Cửa sổ tìm shot xung quanh timestamp script (mốc trung tâm).
SEARCH_WINDOW_BEFORE = float(os.getenv('SEARCH_WINDOW_BEFORE', '6.0'))
SEARCH_WINDOW_AFTER  = float(os.getenv('SEARCH_WINDOW_AFTER', '8.0'))

# Giới hạn thời lượng mỗi clip trong edit plan.
MIN_CLIP_DURATION = float(os.getenv('MIN_CLIP_DURATION', '0.8'))
MAX_CLIP_DURATION = float(os.getenv('MAX_CLIP_DURATION', '6.0'))

# Shot không được tái dùng quá gần (s) nếu có lựa chọn khác; sai số khớp voice (s).
MAX_REUSE_DISTANCE   = float(os.getenv('MAX_REUSE_DISTANCE', '30.0'))
VOICE_SYNC_TOLERANCE = float(os.getenv('VOICE_SYNC_TOLERANCE', '0.25'))

# Lật gương ngang (hflip) SO LE theo từng segment trong smart-shot editor:
# segment chẵn bị lật, segment lẻ giữ nguyên — tạo nhịp đảo cảnh liên tục.
SMART_SHOT_ALTERNATE_FLIP = os.getenv('SMART_SHOT_ALTERNATE_FLIP', '1') not in ('0', 'false', 'False')

# Zoom ngẫu nhiên trong smart-shot: mỗi cảnh phóng to ZOOM% vào MỘT vị trí ngẫu nhiên
# (Ken Burns tĩnh) để tạo chuyển động/đa dạng khi các cảnh nối nhau. Đặt 100 để tắt.
SMART_SHOT_ZOOM_PERCENT = float(os.getenv('SMART_SHOT_ZOOM_PERCENT', '125'))

# Tăng tốc ngẫu nhiên từng CẢNH trong smart-shot: hệ số S trong [MIN, MAX], mỗi cảnh
# ngẫu nhiên riêng. Edit plan lấy thêm nguồn ~S lần rồi phát nhanh (setpts=1/S) → tổng
# thời lượng đầu ra vẫn khớp đúng lời bình; nguồn lấy KHÔNG vượt thời lượng cảnh gốc
# (shot) có sẵn (sẽ tự rút S xuống nếu shot không đủ). Đặt MAX=1 để tắt.
SMART_SHOT_SPEED_MIN = float(os.getenv('SMART_SHOT_SPEED_MIN', '1.0'))
SMART_SHOT_SPEED_MAX = float(os.getenv('SMART_SHOT_SPEED_MAX', '1.5'))

# Đảo NGẪU NHIÊN thứ tự các shot trong cảnh nhiều-shots (>=2 shot) trước khi nối,
# tạo nhịp đổi cảnh không đoán trước. Đặt '0' để tắt.
SMART_SHOT_SHUFFLE = os.getenv('SMART_SHOT_SHUFFLE', '1') not in ('0', 'false', 'False')

# Chạy NGƯỢC (reverse) một số shot trong smart-shot: số shot reverse mỗi cảnh nằm trong
# [1/3, 1/2] số shot của cảnh đó, không có chuỗi quá 2 shot reverse liền kề, ưu tiên
# shot ngắn (<= SHOT_REVERSE_MAX_SEC). Khi bật, render clip theo chiều từ cuối về đầu.
SMART_SHOT_REVERSE = os.getenv('SMART_SHOT_REVERSE', '1') not in ('0', 'false', 'False')
SHOT_REVERSE_MAX_SEC = float(os.getenv('SHOT_REVERSE_MAX_SEC', '2.0'))

# Reverse buffer RAM theo clip (1080p30 ≈ dur×93MB): clip reverse dài hơn ngưỡng này
# được chia thành các cửa sổ nối tiếp (mỗi cửa sổ reverse độc lập) rồi ghép lại, để
# RAM ffmpeg luôn ≤ ~500MB — tránh tràn sang pagefile gây disk 100% trên máy 16GB RAM
# khi render song song. Clip ≤ ngưỡng giữ nguyên reverse liền mạch một lần.
REVERSE_CHUNK_SEC = float(os.getenv('REVERSE_CHUNK_SEC', '5.0'))

# OP/ED: tắt mặc định (chưa có AI detect). Khi bật, bỏ qua các shot trong khoảng này.
SKIP_INTRO_OUTRO = os.getenv('SKIP_INTRO_OUTRO', '0') not in ('0', 'false', 'False')
INTRO_SKIP_SECONDS = float(os.getenv('INTRO_SKIP_SECONDS', '0.0'))
OUTRO_SKIP_SECONDS = float(os.getenv('OUTRO_SKIP_SECONDS', '0.0'))

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.6-flash')

GEMINI_MODELS = [
    {'id': 'gemini-3.6-flash', 'name': 'Gemini 3.6 Flash (mặc định ổn định)'},
    {'id': 'gemini-3.7-flash', 'name': 'Gemini 3.7 Flash'},
    {'id': 'gemini-3.5-flash', 'name': 'Gemini 3.5 Flash'},
    {'id': 'gemini-3.8-flash', 'name': 'Gemini 3.8 Flash (thử nghiệm)'},
    {'id': 'gemini-3.5-flash-lite', 'name': 'Gemini 3.5 Flash Lite'},
    {'id': 'gemini-3-flash-preview', 'name': 'Gemini 3 Flash Preview'},
    {'id': 'gemini-3.1-flash-lite', 'name': 'Gemini 3.1 Flash Lite'},
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_data_dir() -> str:
    """Thư mục dữ liệu runtime — cho phép đặt NGOÀI thư mục phiên bản.

    Ưu tiên env ANIME_DATA_DIR (set qua .env hoặc biến môi trường hệ thống, vd `setx`).
    Nhờ vậy nâng cấp phiên bản = thay code, dữ liệu (DB, video, cache, profile Chrome)
    vẫn nằm nguyên ở thư mục dùng chung, KHÔNG phải copy sang bản mới.
    """
    raw = (os.getenv('ANIME_DATA_DIR') or '').strip().strip('"').strip("'")
    if not raw:
        return os.path.join(BASE_DIR, 'data')
    raw = os.path.expandvars(os.path.expanduser(raw))
    if not os.path.isabs(raw):
        raw = os.path.join(BASE_DIR, raw)
    return os.path.abspath(raw)


# ── Dữ liệu runtime (mọi thứ sinh ra khi chạy nằm gọn trong DATA_DIR) ──
DATA_DIR           = _resolve_data_dir()

# Nạp thêm .env dùng chung trong DATA_DIR (nếu có) để key cấu hình cũng đi theo dữ liệu.
# Không override: .env cạnh code (nếu có) vẫn thắng.
load_dotenv(os.path.join(DATA_DIR, '.env'))

DB_DIR             = os.path.join(DATA_DIR, 'db')
UPLOAD_DIR         = os.path.join(DATA_DIR, 'uploads')
MEDIA_DIR          = os.path.join(DATA_DIR, 'media')
OUTPUT_DIR         = MEDIA_DIR  # tên cũ — giữ để tương thích URL /output và /media
SEGMENTS_DIR       = os.path.join(MEDIA_DIR, 'segments')
AUDIO_DIR          = os.path.join(MEDIA_DIR, 'audio')
FINAL_DIR          = os.path.join(MEDIA_DIR, 'final')
MANUAL_DIR         = os.path.join(MEDIA_DIR, 'manual')
VOICE_REF_DIR      = os.path.join(DATA_DIR, 'voice_refs')   # mẫu giọng clone per-project
CACHE_DIR          = os.path.join(DATA_DIR, 'cache')
LOGS_DIR           = os.path.join(DATA_DIR, 'logs')
TEMP_DIR           = os.path.join(DATA_DIR, 'tmp')
TASK_WORK_ROOT     = os.path.join(DATA_DIR, 'work')
CHROME_PROFILE_DIR = os.path.join(DATA_DIR, 'chrome_profile')  # profile Chrome riêng cho automation CDP
STATIC_DIR         = os.path.join(BASE_DIR, 'static')

for path in [DATA_DIR, DB_DIR, UPLOAD_DIR, MEDIA_DIR, SEGMENTS_DIR, AUDIO_DIR, FINAL_DIR,
             MANUAL_DIR, VOICE_REF_DIR, CACHE_DIR, LOGS_DIR, TEMP_DIR,
             TASK_WORK_ROOT, CHROME_PROFILE_DIR, STATIC_DIR]:
    os.makedirs(path, exist_ok=True)

# --- Tự động hóa Google AI Studio (chế độ manual) ---
# Profile Chrome thật mà tool điều khiển (đã đăng nhập Google AI Studio).
AI_STUDIO_PROFILE = os.getenv('AI_STUDIO_PROFILE', 'Profile 7')
AI_STUDIO_USER_DATA = os.getenv('AI_STUDIO_USER_DATA') or None  # None → mặc định LOCALAPPDATA\Google\Chrome\User Data

# Upload video lên AI Studio qua Playwright CDP chỉ tin cậy với file NHỎ.
# Playwright chặn file >50MB khi browser KHÔNG do Playwright launch (lỗi
# "Cannot transfer files larger than 50Mb to a browser not co-located with the
# server"). Ngưỡng dưới 50MB để có lề an toàn → automation nén bản ≤
# AI_STUDIO_UPLOAD_MAX_MB (giữ âm thanh + fps nguồn qua NVENC GPU) trước khi đính kèm.
# 38MB = lề an toàn thực tế: file ~44MB (sát ngưỡng 45) gây FileChooser.set_files timeout
# trên browser ngoài CDP (treo quanh 40–46MB); ~40MB/35MB upload ổn định.
AI_STUDIO_UPLOAD_MAX_MB = int(os.getenv('AI_STUDIO_UPLOAD_MAX_MB', '38'))

OUTPUT_RESOLUTION = (1920, 1080)
OUTPUT_FPS = 30
# ── YouTube output encoding (áp dụng cho mọi video output, trừ video nén gửi Gemini) ──
# VBR + CQ: giữ chất lượng theo ngưỡng CQ, bitrate tự co giãn theo độ phức tạp cảnh
# (anime màu bẹt → bitrate thực tế thấp hơn target nhiều) thay vì CBR 8M cứng.
OUTPUT_VIDEO_BITRATE = os.getenv('OUTPUT_VIDEO_BITRATE', '5M')    # VBR target
OUTPUT_VIDEO_MAXRATE = os.getenv('OUTPUT_VIDEO_MAXRATE', '8M')    # VBR trần (giữ đỉnh cảnh hành động)
OUTPUT_VIDEO_CQ = int(os.getenv('OUTPUT_VIDEO_CQ', '26'))         # NVENC CQ 0-51, càng nhỏ càng nét (26 ≈ cân bằng)
OUTPUT_NVENC_PRESET = os.getenv('OUTPUT_NVENC_PRESET', 'p3')      # p1 nhanh nhất/nặng nhất → p3/p4 cân bằng
OUTPUT_GOP_SECONDS   = 2                                          # GOP = FPS × 2s = 60 frames @ 30fps
OUTPUT_AUDIO_BITRATE = os.getenv('OUTPUT_AUDIO_BITRATE', '128k')  # AAC (lời bình → 128k đủ, tiết kiệm ~0.5MB/phút)
OUTPUT_AUDIO_RATE    = 48000                                      # 48 kHz

# ── Free-order narrative: AI tự chọn, đảo mạch kể, timestamp không tăng dần ──
FREE_ORDER_DEFAULT = os.getenv('FREE_ORDER_DEFAULT', '0') not in ('0', 'false', 'False')

# ── Chỉnh cảnh kiểu "2 nửa đổi chỗ" ──
# Mỗi cảnh (1 dòng AI = đoạn [st,et] video gốc) được chia ĐỀU làm 2 phần P1-P2
# (P1 lấy từ ngay đầu cảnh, P2 lấy từ giữa), rồi ghép lại đổi chỗ P2 → P1
# (nửa sau lên trước) trong video tóm tắt.
# Lời bình/TTS của cảnh vẫn chạy xuyên suốt; toàn mạch cắt/khớp âm giữ nguyên.
# Bật = True, tắt = False (quay về mỗi cảnh là 1 mảnh liên tục như cũ).
VIDEO_THIRDS_REORDER = bool(os.getenv('VIDEO_THIRDS_REORDER', '1') not in ('0', 'false', 'False'))

# --- Má»¥c tiÃªu video tÃ³m táº¯t cuá»‘i (backend Æ°á»›c lÆ°á»£ng Ä‘á»ƒ nhÃ©t vÃ o prompt) ---
# Tốc độ đọc TTS ĐO THỰC từ các tập đã chạy (giọng capcut_BV421_vivn_streaming):
# trung bình 4.62 từ/giây = 277 từ/phút (các tập ghi nhận 4.44–4.76 wps, thấp hơn giả định 330 cũ ~19%).
# → 5 phút ≈ 1,385 từ | 7 phút ≈ 1,940 từ | 9 phút ≈ 2,490 từ
WORDS_PER_MINUTE = 277.0
SEGMENTS_PER_MINUTE = 6.67    # mật độ phân đoạn (~20s/cảnh gốc)

# 3 mốc thời lượng video tóm tắt — target_sec là mốc CHÍNH XÁC, dải ±20s cho AI linh hoạt.
# target_words: mục tiêu tổng từ LÀM TRÒN theo độ dài (1500/2000/2500) — ở 4.62 từ/giây
# ứng với ~5.4/7.2/9.0 phút đọc; prompt siết ngân sách từ/dòng để AI trả sát target ngay lượt đầu.
# (Không còn vòng retry kịch bản trong gemini_service — số cảnh do AI tự chọn, mỗi cảnh ~20 từ.)
DETAIL_LEVELS = {
    'ngan': {'name': 'Ngắn (~5 phút)',  'target_sec': 300, 'min_sec': 280, 'max_sec': 320, 'target_words': 1500},
    'vua':  {'name': 'Vừa (~7 phút)',   'target_sec': 420, 'min_sec': 400, 'max_sec': 440, 'target_words': 2000},
    'dai':  {'name': 'Dài (~9 phút)',   'target_sec': 540, 'min_sec': 520, 'max_sec': 560, 'target_words': 2500},
}
DEFAULT_DETAIL = 'vua'

HOST = '0.0.0.0'
PORT = 8000

def _load_capcut_voices():
    """Náº¡p giá» ng CapCut tiáº¿ng Viá»‡t tá»« Voice.json (module capcut_tts_api)."""
    import json
    voices = {}
    voice_json = os.path.join(BASE_DIR, 'Voice.json')
    if os.path.exists(voice_json):
        try:
            with open(voice_json, encoding='utf-8') as fp:
                data = json.load(fp)
        except Exception:
            data = []
        for item in data:
            vt = item.get('voice_type') or ''
            if not vt:
                continue
            key = 'capcut_' + vt
            voices[key] = {
                'name': f"CapCut - {item.get('display_name') or vt}",
                'type': 'capcut',
                'id': vt,
                'resource_id': item.get('resource_id', ''),
            }
    return voices


VOICESTUDIO_API_BASE = os.getenv('VOICESTUDIO_API_BASE', 'http://127.0.0.1:3900/v1').rstrip('/')
VOICESTUDIO_TIMEOUT = int(os.getenv('VOICESTUDIO_TIMEOUT', '120'))
VOICESTUDIO_DEFAULT_MODEL = os.getenv('VOICESTUDIO_DEFAULT_MODEL', 'tts-1')
# Tốc độ đọc của VoiceStudio TTS (0.5 = chậm một nửa, 2.0 = gấp đôi tốc độ bình thường).
# Áp dụng cho mọi tập trừ khi bị override bởi tham số riêng của giọng/tập.
VOICESTUDIO_SPEED = max(0.5, min(2.0, float(os.getenv('VOICESTUDIO_SPEED', '1.0'))))


def _load_voicestudio_voices():
    """Giọng VoiceStudio local (chỉ tiếng Việt, debpalash/VoiceStudio)."""
    voices = {
        'vs_default': {
            'name': 'VoiceStudio VI - Tự động (local)',
            'type': 'voicestudio',
            'id': 'default',
        },
        'vs_female': {
            'name': 'VoiceStudio VI - Nữ (local)',
            'type': 'voicestudio',
            'id': 'female',
        },
        'vs_male': {
            'name': 'VoiceStudio VI - Nam (local)',
            'type': 'voicestudio',
            'id': 'male',
        },
        'vs_clone': {
            'name': 'VoiceStudio VI - Clone theo phim (local)',
            'type': 'voicestudio',
            'id': 'clone',
        },
    }
    # Cố gắng nạp thêm danh sách profile/voice thực tế từ VoiceStudio nếu server đang chạy
    try:
        from backend.services.voicestudio_service import list_voices
        discovered = list_voices(timeout=0.6)
        for item in discovered:
            vid = item.get('id')
            if vid and f'vs_profile_{vid}' not in voices:
                voices[f'vs_profile_{vid}'] = {
                    'name': item.get('name') or f'VoiceStudio - {vid}',
                    'type': 'voicestudio',
                    'id': vid,
                }
    except Exception:
        pass
    # Nạp giọng custom đã nhân bản từ registry đĩa (persist qua restart,
    # không phụ thuộc VoiceStudio server có đang chạy hay không).
    try:
        import json as _json
        _reg_file = os.path.join(VOICE_REF_DIR, 'voicestudio_voices.json')
        if os.path.isfile(_reg_file):
            with open(_reg_file, encoding='utf-8') as _fp:
                _items = _json.load(_fp)
            if isinstance(_items, list):
                for _it in _items:
                    if not isinstance(_it, dict):
                        continue
                    _vid = str(_it.get('id') or '').strip()
                    if not _vid:
                        continue
                    _key = f'vs_custom_{_vid}'
                    if _key in voices:
                        continue
                    _pid = str(_it.get('profile_id') or _vid).strip() or _vid
                    _name = str(_it.get('name') or _vid).strip()[:40] or _vid
                    voices[_key] = {
                        'name': f'VoiceStudio - {_name}',
                        'type': 'voicestudio',
                        'id': _pid,
                        'custom': True,
                    }
    except Exception:
        pass
    return voices


VOICES = {
    **_load_voicestudio_voices(),
    **_load_capcut_voices(),
}

# Mặc định = VoiceStudio (local); còn CapCut khi cần.
DEFAULT_VOICE = 'vs_default' if 'vs_default' in VOICES else (next(iter(VOICES)) if VOICES else '')

# ════════════════════════════════════════════════════════════════════
#  ADMIN SETTINGS — runtime-configurable via /admin panel
# ════════════════════════════════════════════════════════════════════
import json as _json

ADMIN_SETTINGS_FILE = os.path.join(DATA_DIR, 'admin_settings.json')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

ADMIN_SCHEMA = {
    'OUTPUT_FPS':               {'type': 'int',    'default': 30,     'min': 15, 'max': 60, 'label': 'FPS', 'group': 'encoding'},
    'OUTPUT_VIDEO_BITRATE':     {'type': 'str',    'default': '5M',   'label': 'Video Bitrate (VBR target)', 'group': 'encoding'},
    'OUTPUT_VIDEO_MAXRATE':     {'type': 'str',    'default': '8M',   'label': 'Video Maxrate (VBR trần)', 'group': 'encoding'},
    'OUTPUT_VIDEO_CQ':          {'type': 'int',    'default': 26,     'min': 18, 'max': 32, 'label': 'Video CQ (càng nhỏ càng nét)', 'group': 'encoding'},
    'OUTPUT_NVENC_PRESET':      {'type': 'str',    'default': 'p3',   'options': ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7'], 'label': 'NVENC Preset', 'group': 'encoding'},
    'OUTPUT_GOP_SECONDS':       {'type': 'int',    'default': 2,      'min': 1, 'max': 5, 'label': 'GOP (giây)', 'group': 'encoding'},
    'OUTPUT_AUDIO_BITRATE':     {'type': 'str',    'default': '128k', 'label': 'Audio Bitrate', 'group': 'encoding'},
    'OUTPUT_AUDIO_RATE':        {'type': 'int',    'default': 48000,  'label': 'Audio Sample Rate', 'group': 'encoding'},
    'EDIT_MODE_DEFAULT':        {'type': 'str',    'default': 'smart_shot', 'options': ['legacy', 'smart_shot'], 'label': 'Edit Mode', 'group': 'smart_shot'},
    'SHOT_SCENE_THRESHOLD':     {'type': 'float',  'default': 0.2,    'min': 0.05, 'max': 0.9, 'label': 'Scene Threshold', 'group': 'smart_shot'},
    'SHOT_DETECTOR':            {'type': 'str',    'default': 'auto',  'options': ['auto', 'ffmpeg', 'pyscenedetect'], 'label': 'Shot Detector', 'group': 'smart_shot'},
    'PYSCENE_METHOD':           {'type': 'str',    'default': 'adaptive', 'options': ['adaptive', 'content'], 'label': 'PyScene Method', 'group': 'smart_shot'},
    'PYSCENE_ADAPTIVE_THRESHOLD': {'type': 'float', 'default': 3.0,   'min': 0.2, 'max': 20.0, 'label': 'PyScene Adaptive Threshold', 'group': 'smart_shot'},
    'PYSCENE_MIN_CONTENT_VAL':  {'type': 'float',  'default': 15.0,   'min': 1.0, 'max': 60.0, 'label': 'PyScene Min Content Val', 'group': 'smart_shot'},
    'PYSCENE_CONTENT_THRESHOLD': {'type': 'float',  'default': 27.0,   'min': 5.0, 'max': 60.0, 'label': 'PyScene Content Threshold', 'group': 'smart_shot'},
    'PYSCENE_MIN_SCENE_LEN':    {'type': 'float',  'default': 0.4,    'min': 0.1, 'max': 2.0, 'label': 'PyScene Min Scene Len (s)', 'group': 'smart_shot'},
    'PYSCENE_FRAME_SKIP':       {'type': 'int',    'default': 2,      'min': 0, 'max': 5, 'label': 'PyScene Frame Skip (0=tất cả, 2=cách 2 frame ~3x tốc độ)', 'group': 'smart_shot'},
    'PYSCENE_BACKEND':          {'type': 'str',    'default': 'auto', 'options': ['auto', 'pyav', 'opencv'], 'label': 'PyScene Backend (pyav nhanh hơn)', 'group': 'smart_shot'},
    'PYSCENE_USE_PROXY':        {'type': 'bool',   'default': True,   'label': 'PyScene Dùng Video Nén 480p (nhanh gấp 3-4x)', 'group': 'smart_shot'},
    'SHOT_MERGE_MIN':           {'type': 'float',  'default': 0.5,    'min': 0.1, 'max': 3.0, 'label': 'Shot Merge Min (s)', 'group': 'smart_shot'},
    'SHOT_MIN_DURATION':        {'type': 'float',  'default': 0.8,    'min': 0.2, 'max': 5.0, 'label': 'Shot Min Duration (s)', 'group': 'smart_shot'},
    'SHOT_MAX_DURATION':        {'type': 'float',  'default': 8.0,    'min': 2.0, 'max': 30.0, 'label': 'Shot Max Duration (s)', 'group': 'smart_shot'},
    'SEARCH_WINDOW_BEFORE':     {'type': 'float',  'default': 6.0,    'min': 1, 'max': 20, 'label': 'Search Window Before (s)', 'group': 'smart_shot'},
    'SEARCH_WINDOW_AFTER':      {'type': 'float',  'default': 8.0,    'min': 1, 'max': 20, 'label': 'Search Window After (s)', 'group': 'smart_shot'},
    'MIN_CLIP_DURATION':        {'type': 'float',  'default': 0.8,    'min': 0.2, 'max': 3.0, 'label': 'Min Clip Duration (s)', 'group': 'smart_shot'},
    'MAX_CLIP_DURATION':        {'type': 'float',  'default': 6.0,    'min': 2.0, 'max': 15.0, 'label': 'Max Clip Duration (s)', 'group': 'smart_shot'},
    'MAX_REUSE_DISTANCE':       {'type': 'float',  'default': 30.0,   'label': 'Max Reuse Distance (s)', 'group': 'smart_shot'},
    'VOICE_SYNC_TOLERANCE':     {'type': 'float',  'default': 0.25,   'min': 0.05, 'max': 1.0, 'label': 'Voice Sync Tolerance (s)', 'group': 'smart_shot'},
    'SMART_SHOT_ALTERNATE_FLIP':{'type': 'bool',   'default': True,   'label': 'Alternate Flip', 'group': 'smart_shot'},
    'SMART_SHOT_ZOOM_PERCENT':  {'type': 'float',  'default': 125.0,  'min': 100, 'max': 200, 'label': 'Zoom Percent', 'group': 'smart_shot'},
    'SMART_SHOT_SPEED_MIN':     {'type': 'float',  'default': 1.0,    'min': 1.0, 'max': 3.0, 'label': 'Speed Min', 'group': 'smart_shot'},
    'SMART_SHOT_SPEED_MAX':     {'type': 'float',  'default': 1.5,    'min': 1.0, 'max': 5.0, 'label': 'Speed Max', 'group': 'smart_shot'},
    'SMART_SHOT_REVERSE':       {'type': 'bool',   'default': True,   'label': 'Reverse Short Shots', 'group': 'smart_shot'},
    'SHOT_REVERSE_MAX_SEC':     {'type': 'float',  'default': 2.0,    'min': 0.5, 'max': 6.0, 'label': 'Reverse Max Duration (s)', 'group': 'smart_shot'},
    'REVERSE_CHUNK_SEC':        {'type': 'float',  'default': 5.0,    'min': 2.0, 'max': 15.0, 'label': 'Reverse Chunk (s, giới hạn RAM)', 'group': 'smart_shot'},
    'SMART_SHOT_SHUFFLE':       {'type': 'bool',   'default': True,   'label': 'Shuffle Shots', 'group': 'smart_shot'},
    'VIDEO_THIRDS_REORDER':     {'type': 'bool',   'default': True,   'label': 'Thirds Reorder', 'group': 'smart_shot'},
    'SKIP_INTRO_OUTRO':         {'type': 'bool',   'default': False,  'label': 'Skip Intro/Outro', 'group': 'smart_shot'},
    'INTRO_SKIP_SECONDS':       {'type': 'float',  'default': 0.0,    'min': 0, 'max': 120, 'label': 'Intro Skip (s)', 'group': 'smart_shot'},
    'OUTRO_SKIP_SECONDS':       {'type': 'float',  'default': 0.0,    'min': 0, 'max': 120, 'label': 'Outro Skip (s)', 'group': 'smart_shot'},
    'MAX_NETWORK_EPISODES':     {'type': 'int',    'default': 2,      'min': 1, 'max': 8, 'label': 'Max Network Episodes', 'group': 'concurrency'},
    'MAX_INFLIGHT_EPISODES':    {'type': 'int',    'default': 6,      'min': 1, 'max': 20, 'label': 'Max Inflight Episodes', 'group': 'concurrency'},
    'WORDS_PER_MINUTE':         {'type': 'float',  'default': 277.0,  'label': 'Words Per Minute', 'group': 'tts'},
    'SEGMENTS_PER_MINUTE':      {'type': 'float',  'default': 6.67,   'label': 'Segments Per Minute', 'group': 'tts'},
    'GEMINI_MODEL':             {'type': 'str',    'default': 'gemini-3.6-flash', 'options': [m['id'] for m in GEMINI_MODELS], 'label': 'Gemini Model', 'group': 'tts'},
    'VOICESTUDIO_API_BASE':     {'type': 'str',    'default': 'http://127.0.0.1:3900/v1', 'label': 'VoiceStudio API Base', 'group': 'tts'},
    'VOICESTUDIO_TIMEOUT':      {'type': 'int',    'default': 120,    'min': 10, 'max': 300, 'label': 'VoiceStudio Timeout (s)', 'group': 'tts'},
    'VOICESTUDIO_SPEED':        {'type': 'float',  'default': 1.0,    'min': 0.5, 'max': 2.0, 'label': 'VoiceStudio Speed (0.5–2.0)', 'group': 'tts'},
    'CHARACTER_NAME_MODE':      {'type': 'str',    'default': 'romaji', 'options': ['vietnamese', 'romaji'], 'label': 'Chế độ tên nhân vật', 'group': 'smart_shot'},
    'CHARACTER_REGISTRY':       {'type': 'list',   'default': [], 'label': 'Character Registry', 'group': 'smart_shot'},
}


def _coerce(value, typ):
    """Ép kiểu value theo schema type."""
    if typ == 'bool':
        if isinstance(value, bool):
            return value
        return str(value).lower() not in ('0', 'false', 'false', 'no', '')
    if typ == 'int':
        return int(value)
    if typ == 'float':
        return float(value)
    if typ == 'list':
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [v.strip() for v in value.split(',') if v.strip()]
        return []
    if typ == 'object_list':
        if isinstance(value, list):
            return value
        return []
    return str(value)

GEMINI_MODELS_FILE = os.path.join(DATA_DIR, 'gemini_models.json')


def _load_models():
    """Nạp danh sách model từ gemini_models.json (nếu có) → ghi đè list mặc định."""
    if not os.path.exists(GEMINI_MODELS_FILE):
        return
    try:
        with open(GEMINI_MODELS_FILE, encoding='utf-8') as f:
            saved = _json.load(f)
        if isinstance(saved, list) and saved:
            globals()['GEMINI_MODELS'] = saved
            _refresh_model_options()
    except Exception:
        pass


def _save_models(models: list) -> list:
    """Ghi danh sách model ra gemini_models.json. Trả về list đã lưu."""
    os.makedirs(os.path.dirname(GEMINI_MODELS_FILE), exist_ok=True)
    with open(GEMINI_MODELS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(models, f, ensure_ascii=False, indent=2)
    globals()['GEMINI_MODELS'] = models
    _refresh_model_options()
    return models


def get_models() -> list:
    """Trả về danh sách model hiện tại."""
    return list(globals().get('GEMINI_MODELS', GEMINI_MODELS))


def add_model(model_id: str, name: str = '') -> list:
    """Thêm một model mới vào danh sách. Trả về list mới."""
    model_id = model_id.strip()
    if not model_id:
        raise ValueError('Model ID không được rỗng')
    models = get_models()
    if any(m.get('id') == model_id for m in models):
        raise ValueError(f'Model {model_id} đã tồn tại')
    models.append({'id': model_id, 'name': name.strip() or model_id})
    return _save_models(models)


def update_model(index: int, model_id: str = None, name: str = None) -> list:
    """Cập nhật model tại index. Trả về list mới."""
    models = get_models()
    if not (0 <= index < len(models)):
        raise ValueError('Index không hợp lệ')
    if model_id is not None:
        model_id = model_id.strip()
        if not model_id:
            raise ValueError('Model ID không được rỗng')
        if any(m.get('id') == model_id and i != index for i, m in enumerate(models)):
            raise ValueError(f'Model {model_id} đã tồn tại')
        models[index]['id'] = model_id
    if name is not None:
        models[index]['name'] = name.strip() or models[index]['id']
    return _save_models(models)


def remove_model(index: int) -> list:
    """Xóa model tại index. Trả về list mới."""
    models = get_models()
    if not (0 <= index < len(models)):
        raise ValueError('Index không hợp lệ')
    removed = models.pop(index)
    new = _save_models(models)
    # Nếu model mặc định bị xóa → set lại model đầu tiên
    cur = globals().get('GEMINI_MODEL')
    if cur == removed.get('id') and new:
        globals()['GEMINI_MODEL'] = new[0]['id']
    return new


def _refresh_model_options():
    """Cập nhật options cho GEMINI_MODEL trong schema để phản chiếu danh sách model."""
    ids = [m['id'] for m in get_models()]
    if 'GEMINI_MODEL' in ADMIN_SCHEMA:
        ADMIN_SCHEMA['GEMINI_MODEL']['options'] = ids


def load_admin_settings():
    """Đọc admin_settings.json → apply vào config module globals. Trả về dict settings."""
    if not os.path.exists(ADMIN_SETTINGS_FILE):
        return {}
    try:
        with open(ADMIN_SETTINGS_FILE, encoding='utf-8') as f:
            saved = _json.load(f)
    except Exception:
        return {}
    applied = {}
    for key, schema in ADMIN_SCHEMA.items():
        if key in saved:
            try:
                val = _coerce(saved[key], schema['type'])
                # Clamp numeric
                if 'min' in schema:
                    val = max(schema['min'], val)
                if 'max' in schema:
                    val = min(schema['max'], val)
                # Validate options
                if 'options' in schema and val not in schema['options']:
                    continue
                globals()[key] = val
                applied[key] = val
            except Exception:
                pass
    # Rebuild NETWORK_EPISODE_LOCK nếu MAX_NETWORK_EPISODES thay đổi
    if 'MAX_NETWORK_EPISODES' in applied:
        new_lock = threading.BoundedSemaphore(applied['MAX_NETWORK_EPISODES'])
        globals()['NETWORK_EPISODE_LOCK'] = new_lock
    # Rebuild VOICES nếu DEFAULT_VOICE thay đổi
    if 'DEFAULT_VOICE' in applied and applied['DEFAULT_VOICE']:
        globals()['DEFAULT_VOICE'] = applied['DEFAULT_VOICE']
    return applied


def _propagate_runtime(validated: dict) -> int:
    """Đẩy giá trị mới vào các module đã `from config import X` (bind giá trị tĩnh
    lúc import) để lượt render mới nhận ngay không cần restart server. Chỉ set các
    key module đó đã có (không nhét thuộc tính lạ). Import lazy để tránh circular."""
    import importlib
    count = 0
    for mod_name in ('backend.services.video_service', 'backend.main',
                     'backend.api.deps', 'backend.api.pipeline',
                     'backend.api.routers.system', 'backend.api.routers.projects',
                     'backend.api.routers.manual', 'backend.api.routers.voices',
                     'backend.api.routers.admin',
                     'backend.services.gemini_service', 'backend.services.tts_service'):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for key, val in validated.items():
            if key in ADMIN_SCHEMA and hasattr(mod, key):
                try:
                    setattr(mod, key, val)
                    count += 1
                except Exception:
                    pass
    return count


def save_admin_settings(updates: dict) -> dict:
    """Ghi updates vào admin_settings.json + apply runtime. Trả về settings hoàn chỉnh."""
    existing = {}
    if os.path.exists(ADMIN_SETTINGS_FILE):
        try:
            with open(ADMIN_SETTINGS_FILE, encoding='utf-8') as f:
                existing = _json.load(f)
        except Exception:
            existing = {}

    # Validate + coerce
    validated = {}
    for key, val in updates.items():
        if key not in ADMIN_SCHEMA:
            continue
        schema = ADMIN_SCHEMA[key]
        try:
            val = _coerce(val, schema['type'])
            if 'min' in schema:
                val = max(schema['min'], val)
            if 'max' in schema:
                val = min(schema['max'], val)
            if 'options' in schema and val not in schema['options']:
                continue
            validated[key] = val
        except Exception:
            continue

    existing.update(validated)
    os.makedirs(os.path.dirname(ADMIN_SETTINGS_FILE), exist_ok=True)
    with open(ADMIN_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(existing, f, ensure_ascii=False, indent=2)

    # Apply runtime
    for key, val in existing.items():
        if key in ADMIN_SCHEMA:
            try:
                globals()[key] = _coerce(val, ADMIN_SCHEMA[key]['type'])
            except Exception:
                pass

    if 'MAX_NETWORK_EPISODES' in existing:
        new_lock = threading.BoundedSemaphore(int(existing['MAX_NETWORK_EPISODES']))
        globals()['NETWORK_EPISODE_LOCK'] = new_lock

    _refresh_model_options()
    propagated = _propagate_runtime(validated)
    existing['_applied_runtime'] = propagated
    return existing


def get_current_settings() -> dict:
    """Trả về dict {key: current_value} cho mọi setting trong schema."""
    result = {}
    for key, schema in ADMIN_SCHEMA.items():
        result[key] = globals().get(key, schema['default'])
    return result


# Load saved settings at startup
_load_models()  # nạp danh sách model tùy chỉnh trước khi apply settings (GEMINI_MODEL cần options đúng)
load_admin_settings()
