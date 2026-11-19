"""TTS provider: VoiceStudio (debpalash/VoiceStudio) local API.

VoiceStudio la nen tang TTS / Voice Cloning chay local thay the cho ElevenLabs,
cung cap API tuong thich chuan OpenAI tai http://127.0.0.1:3900/v1.

Cac endpoint su dung:
- POST /v1/audio/speech: tong hop giong noi
- GET /v1/audio/voices: danh sach giong va profile
- GET /health: kiem tra trang thai hoat dong cua VoiceStudio server
"""
import os
import time
import logging
import subprocess
import requests

logger = logging.getLogger(__name__)

VOICESTUDIO_API_BASE = os.getenv('VOICESTUDIO_API_BASE', 'http://127.0.0.1:3900/v1').rstrip('/')
VOICESTUDIO_TIMEOUT = int(os.getenv('VOICESTUDIO_TIMEOUT', '120'))
VOICESTUDIO_DEFAULT_MODEL = os.getenv('VOICESTUDIO_DEFAULT_MODEL', 'tts-1')

_session: requests.Session | None = None


def get_session() -> requests.Session:
    """Session tái sử dụng kết nối HTTP Keep-Alive để tối ưu tốc độ gọi local."""
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
        _session.mount('http://', adapter)
        _session.mount('https://', adapter)
    return _session


def get_root_url() -> str:
    """Lấy root URL từ API base (vd http://127.0.0.1:3900 từ http://127.0.0.1:3900/v1)."""
    base = VOICESTUDIO_API_BASE
    if base.endswith('/v1'):
        return base[:-3]
    return base


def check_health(timeout: float = 2.0) -> tuple[bool, str]:
    """Kiểm tra nhanh xem VoiceStudio server có đang hoạt động không.

    Dùng requests.get (KHÔNG retry) để khi server local tắt/treo thì fail nhanh,
    tránh việc mỗi lần poll của UI phải chờ nhiều lần timeout.
    """
    root = get_root_url()
    try:
        r = requests.get(f'{root}/health', timeout=timeout)
        if r.status_code == 200:
            return True, 'VoiceStudio đang hoạt động'
    except Exception:
        pass

    try:
        r = requests.get(f'{VOICESTUDIO_API_BASE}/models', timeout=timeout)
        if r.status_code == 200:
            return True, 'VoiceStudio đang hoạt động'
    except Exception as e:
        return False, f'Chưa kết nối được VoiceStudio tại {root}: {e}'

    return False, f'VoiceStudio không phản hồi tại {root}'


def list_voices(timeout: float = 3.0) -> list[dict]:
    """Lấy danh sách các giọng/profiles tiếng Việt từ VoiceStudio API nếu có."""
    voices = []
    # 1. Thử GET /v1/audio/voices
    try:
        r = requests.get(f'{VOICESTUDIO_API_BASE}/audio/voices', timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            items = data.get('voices', data) if isinstance(data, dict) else data
            if isinstance(items, list):
                for item in items:
                    vid = item.get('voice_id') or item.get('id') or ''
                    name = item.get('name') or vid
                    lang = (item.get('language') or item.get('lang') or item.get('locale') or '').lower()
                    # Chỉ giữ tiếng Việt hoặc các profile không chỉ định ngôn ngữ khác
                    if lang and not (lang.startswith('vi') or 'viet' in lang):
                        continue
                    if vid:
                        voices.append({'id': vid, 'name': f'VoiceStudio VI - {name}'})
    except Exception:
        pass

    # 2. Thử GET /profiles (VoiceStudio profile endpoint)
    if not voices:
        try:
            root = get_root_url()
            r = requests.get(f'{root}/profiles', timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                items = data.get('profiles', data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for item in items:
                        vid = item.get('id') or item.get('profile_id') or ''
                        name = item.get('name') or vid
                        lang = (item.get('language') or item.get('lang') or '').lower()
                        if lang and not (lang.startswith('vi') or 'viet' in lang):
                            continue
                        if vid:
                            voices.append({'id': vid, 'name': f'VoiceStudio VI - {name}'})
        except Exception:
            pass

    return voices


def _audio_duration(output_path: str) -> float:
    """Đo thời lượng file audio bằng ffprobe."""
    try:
        from backend.core.config import LOCAL_HARDWARE_LOCK
        with LOCAL_HARDWARE_LOCK:
            res = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
                capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        try:
            return max(1.0, os.path.getsize(output_path) / 16000.0)
        except OSError:
            return 0.0


DEFAULT_VS_VOICES = {
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


def synthesize(text: str, output_path: str, voice: str = 'default',
               model: str = None, speed: float = 1.0) -> float:
    """Tổng hợp giọng nói tiếng Việt từ VoiceStudio qua HTTP API.
    
    Tham số:
    - text: văn bản tiếng Việt cần đọc
    - output_path: đường dẫn lưu file .mp3
    - voice: voice ID hoặc profile ID trong VoiceStudio (mặc định 'default')
    - model: tên model/engine (mặc định tts-1)
    - speed: tốc độ nói (1.0)
    """
    text = (text or '').strip()
    if not text:
        return 0.0

    url = f'{VOICESTUDIO_API_BASE}/audio/speech'
    payload = {
        'model': model or VOICESTUDIO_DEFAULT_MODEL,
        'input': text,
        'voice': voice or 'default',
        'language': 'vi',
        'language_code': 'vi',
        'response_format': 'mp3',
        'speed': float(speed or 1.0),
    }

    session = get_session()
    last_err = None
    for attempt in range(2):
        try:
            logger.info(f'[VoiceStudio] Gọi TTS ({voice}): {text[:50]}... (thử {attempt+1})')
            r = session.post(url, json=payload, timeout=(3.0, VOICESTUDIO_TIMEOUT), stream=True)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=32768):
                        if chunk:
                            f.write(chunk)
                if os.path.isfile(output_path) and os.path.getsize(output_path) > 100:
                    return _audio_duration(output_path)
                raise RuntimeError('VoiceStudio trả về dữ liệu audio rỗng hoặc không hợp lệ')
            elif r.status_code in (429, 503):
                time.sleep(2.0)
                last_err = RuntimeError(f'VoiceStudio máy chủ đang bận (HTTP {r.status_code}): {r.text[:200]}')
            else:
                raise RuntimeError(f'VoiceStudio API lỗi HTTP {r.status_code}: {r.text[:300]}')
        except requests.exceptions.ConnectionError as e:
            root = get_root_url()
            raise RuntimeError(
                f'Không thể kết nối đến VoiceStudio tại {root}. '
                f'Vui lòng khởi động VoiceStudio (hoặc kiểm tra cấu hình VOICESTUDIO_API_BASE).'
            ) from e
        except requests.exceptions.Timeout:
            last_err = RuntimeError(f'VoiceStudio phản hồi quá lâu (quá {VOICESTUDIO_TIMEOUT}s)')
        except Exception as e:
            last_err = e

    raise RuntimeError(f'VoiceStudio TTS thất bại: {last_err}')


def create_profile(name: str, audio_path: str, ref_text: str = '') -> dict:
    """Tao profile giong moi tren VoiceStudio qua POST /profiles."""
    root = get_root_url()
    url = f'{root}/profiles'
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f'Không tìm thấy file audio: {audio_path}')

    with open(audio_path, 'rb') as fp:
        files = {'ref_audio': (os.path.basename(audio_path), fp, 'audio/wav')}
        data = {'name': name}
        if ref_text:
            data['ref_text'] = ref_text
        try:
            r = requests.post(url, data=data, files=files, timeout=60)
            if r.status_code in (200, 201):
                return r.json()
            raise RuntimeError(f'Tạo profile thất bại HTTP {r.status_code}: {r.text[:300]}')
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f'Không thể kết nối đến VoiceStudio tại {root}') from e
