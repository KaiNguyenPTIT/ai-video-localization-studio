import time, json, re, os, threading, logging

logger = logging.getLogger(__name__)

import httpx
from google.genai import Client, types
from backend.core.config import GEMINI_MODEL, GEMINI_UPLOAD_LOCK, WORDS_PER_MINUTE, OUTPUT_DIR
from backend.core import key_pool
from backend.utils.srt_parser import time_to_seconds

# Hard-timeout cho giai đoạn chuyển byte upload lên Gemini (s). Stream upload không bị timeout
# của HttpOptions chặn nên dễ treo vô hạn khi mạng kẹt — đây là cái lưới an toàn.
# Mặc định 600s (10 phút): đủ cho file ~50MB, quá hạn coi như kẹt mạng -> bỏ key, thử key khác.
_UPLOAD_TIMEOUT_SEC = int(os.environ.get('GEMINI_UPLOAD_TIMEOUT_SEC', '600'))


def _client_for(api_key: str, read_timeout: float = 300.0, conn_timeout: float = 30.0) -> Client:
    """Tạo genai Client với pool kết nối BĨ CHẶN + không retry nội bộ.
    Mục đích: ngăn rò rỉ socket (httpx pool của mỗi Client) và để lỗi kết nối/TLS
    fail NHANH để rơi vào budget _UPLOAD_TIMEOUT_SEC bên ngoài thay vì retry vô hạn.
    Client này PHẢI được close() sau khi xong (xem summarize_video finally).
    read_timeout/conn_timeout: trích nhân vật (lite, text-only) chỉ cần 30s/10s,
    còn viết kịch bản video giữ 300s/30s mặc định."""
    return Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=6 * 60 * 1000,
            client_args={
                'limits': httpx.Limits(max_connections=5, max_keepalive_connections=2),
                'timeout': httpx.Timeout(connect=float(conn_timeout), read=float(read_timeout),
                                         write=300.0, pool=float(conn_timeout)),
            },
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _close_client(client) -> None:
    """Đóng genai Client để giải phóng pool kết nối httpx (tránh tích lũy socket CLOSE_WAIT/BOUND)."""
    if client is None:
        return
    try:
        if hasattr(client, 'close'):
            client.close()
    except Exception:
        pass


def _fmt_srt(seconds: float) -> str:
    """Định dạng giây -> chuỗi timestamp HH:MM:SS (không mili-giây)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(round(seconds % 60))
    if s == 60:
        s = 0
        m += 1
        if m == 60:
            m = 0
            h += 1
    return f'{h:02d}:{m:02d}:{s:02d}'


def upload_video_to_gemini(video_path: str, progress_callback=None, api_key=None):
    if not api_key:
        api_key = key_pool.next_key()
    if not api_key:
        raise ValueError('Chưa thiết lập GEMINI_API_KEY!')

    client = _client_for(api_key)
    if progress_callback:
        progress_callback('Đang upload video lên Gemini API...', 10)

    # Truyền byte lên Gemini TUẦN TỰ (từng video một) — giai đoạn tốn băng thông nhất,
    # dễ nghẽn mạng khi nhiều tập chạy song song. generate_content/TTS vẫn song song.
    with GEMINI_UPLOAD_LOCK:
        uploaded = client.files.upload(
            file=video_path,
            config=types.UploadFileConfig(display_name=os.path.basename(video_path))
        )

    # Đợi Gemini giải mã/xử lý video với timeout an toàn (15 phút cho file lớn)
    t0 = time.time()
    timeout = 15 * 60
    while time.time() - t0 < timeout:
        if progress_callback:
            progress_callback('Gemini đang giải mã và xử lý video...', 20)
        f = client.files.get(name=uploaded.name)
        state = getattr(f.state, 'name', str(f.state))
        if state != 'PROCESSING':
            break
        time.sleep(3)

    state = getattr(f.state, 'name', str(f.state))
    if state == 'FAILED':
        _close_client(client)
        detail = ''
        if getattr(f, 'error', None):
            detail = f" ({f.error.code or ''} {f.error.message or ''})"
        raise Exception(f'Upload video lên Gemini thất bại{detail}!')
    if state == 'PROCESSING':
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
        _close_client(client)
        raise Exception('Gemini xử lý video quá lâu (quá 15 phút). Video có thể quá lớn hoặc định dạng không phù hợp.')
    return client, f


def _upload_video_batch(video_path: str, keys: list, progress_callback=None):
    """Upload cùng 1 video lên NHIỀU key. Giai đoạn chậm nhất — chờ Gemini GIẢI MÃ video —
    chạy SONG SONG giữa các key để không cộng dồn thời gian chờ. Mỗi lần chuyển BYTE được bọc
    hard-timeout (_UPLOAD_TIMEOUT_SEC) trên worker tách: stream upload không bị timeout của
    HttpOptions chặn, nên network kẹt sẽ treo — bọc budget để bỏ key đó, không treo vô hạn,
    và KHÔNG giữ GEMINI_UPLOAD_LOCK trong worker (tránh worker treo khóa làm tắc cả app).
    Trả về (prepared, last_err). prepared = [(api_key, gen_client, video_file)]."""
    import concurrent.futures as _cf
    n = len(keys)
    entries, last_err = [], None

    for i, api_key in enumerate(keys, 1):
        try:
            if progress_callback:
                progress_callback(f'Đang upload video lên Gemini API... (key {i}/{n})', 10)
            client = _client_for(api_key)
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            try:
                _fut = _ex.submit(
                    client.files.upload,
                    file=video_path,
                    config=types.UploadFileConfig(display_name=os.path.basename(video_path))
                )
                uploaded = _fut.result(timeout=_UPLOAD_TIMEOUT_SEC)
            except _cf.TimeoutError:
                raise TimeoutError(
                    f'Upload video quá {_UPLOAD_TIMEOUT_SEC}s (kẹt mạng) với key "{api_key[:6]}..."') from None
            finally:
                _ex.shutdown(wait=False)
            entries.append((api_key, client, uploaded))
        except Exception as e:
            # Upload thất bại → đóng client ngay để không rò rỉ socket pool của key này
            _close_client(client)
            last_err = e
            if progress_callback:
                progress_callback(f'Key "{api_key[:6]}..." upload thất bại ({type(e).__name__}), bỏ qua...', 12)

    prepared = []
    if entries:
        def _await_one(entry):
            api_key, client, uploaded = entry
            t0 = time.time()
            timeout = 15 * 60
            while time.time() - t0 < timeout:
                cur = client.files.get(name=uploaded.name)
                state = getattr(cur.state, 'name', str(cur.state))
                if state != 'PROCESSING':
                    return (api_key, client, cur, state)
                time.sleep(3)
            return (api_key, client, uploaded, 'PROCESSING')

        with _cf.ThreadPoolExecutor(max_workers=n) as ex:
            futures = [ex.submit(_await_one, e) for e in entries]
            for fut in _cf.as_completed(futures):
                api_key, client, f, state = fut.result()
                if state in ('FAILED', 'PROCESSING'):
                    _close_client(client)
                    last_err = Exception(f'Gemini giải mã video lỗi với key "{api_key[:6]}..." (state={state})')
                    if progress_callback:
                        progress_callback(f'Key "{api_key[:6]}..." giải mã video lỗi ({state}), bỏ qua...', 22)
                    continue
                prepared.append((api_key, client, f))
    return prepared, last_err


SYSTEM_INSTRUCTION = (
    'Bạn là biên kịch chuyên nghiệp hàng đầu chuyên viết kịch bản lời bình tóm tắt anime (Anime Recap) '
    'để đọc voice-over tiếng Việt cho các kênh review phim triệu view. '
    'TÔN CHỈ CỐT LÕI: Kịch bản phải là MỘT CÂU CHUYỆN LIỀN MẠCH DUY NHẤT, trôi chảy và cuốn hút từ đầu đến cuối. '
    'Các mốc thời gian (MM:SS) chỉ là neo đồng bộ hình ảnh; tuyệt đối không liệt kê hành động rời rạc từng cảnh. '
    'Khi đọc toàn bộ kịch bản, các câu phải móc nối tự nhiên theo quan hệ nhân - quả, cảm xúc và xung đột. '
    'Ngôn từ giàu tính điện ảnh, tự nhiên trong văn nói, ngắt nghỉ nhịp nhàng. '
    'Tên nhân vật phải viết đúng họ tên đã đăng ký, không bao giờ lặp chữ đầu của họ '
    '(đúng: "Hoàng Linh Lâm" — sai: "Hoàng Hoàng Linh Lâm"). '
    'Đầu ra là kịch bản phân cảnh theo đúng định dạng yêu cầu, không kèm bất kỳ lời dẫn hay giải thích nào.'
)


def _fmt_mmss(seconds: float) -> str:
    """Định dạng giây -> MM:SS (dùng cho mốc thời lượng video trong prompt)."""
    seconds = max(0, int(round(seconds)))
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f'{h:02d}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def _build_character_registry_block(characters: list | None = None, name_mode: str = 'romaji') -> str:
    """Tạo khối prompt hướng dẫn AI gọi đúng tên nhân vật.

    - Có danh sách nhân vật: in "NHÂN VẬT ĐÃ BIẾT" + quy ước tên + chống lặp chữ trong họ tên.
    - Chưa có nhân vật đăng ký: vẫn nhắc quy ước tên theo name_mode để ngay tập đầu tiên
      AI đã viết tên đúng (tiếng Việt hoặc Romaji). name_mode: 'vietnamese' → tên tiếng Việt."""
    lines = []
    if characters:
        lines.append('## NHÂN VẬT ĐÃ BIẾT')
        for i, c in enumerate(characters, 1):
            name = c.get('name', '')
            aliases = c.get('aliases', [])
            alias_txt = f' (còn gọi: {", ".join(aliases)})' if aliases else ''
            lines.append(f'{i}. {name}{alias_txt}')
        lines.append('')
        if name_mode == 'romaji':
            lines.append('Quy ước tên: với nhân vật trong danh sách trên, dùng đúng tên gốc Latin hóa (Romaji) như đã đăng ký — tuyệt đối KHÔNG dùng Kanji/Katakana vì TTS tiếng Việt không đọc được.')
        else:
            lines.append('Quy ước tên: với nhân vật trong danh sách trên, dùng đúng tên tiếng Việt như đã đăng ký.')
        first_name = characters[0].get('name', '') if characters else ''
        if first_name and ' ' in first_name:
            first_word = first_name.split(' ', 1)[0]
            lines.append(
                f'Viết họ tên đầy đủ, đúng chính tả, không lặp thêm chữ nào của họ/tên '
                f'(đúng: "{first_name}" — sai: "{first_word} {first_name}").'
            )
        multi = [c.get('name', '') for c in characters if len((c.get('name') or '').split()) >= 2]
        if multi:
            lines.append('QUAN TRỌNG: Tự rà lại tên nhân vật NGAY TRƯỚC khi xuất kịch bản.')
            lines.append('Tuyệt đối không được viết lặp chữ đầu của họ/tên. Với từng nhân vật:')
            for name in multi:
                head = name.split(' ', 1)[0]
                lines.append(f'- "{name}" là ĐÚNG — "{head} {name}" là SAI, phải loại bỏ.')
            lines.append(
                'Mọi dòng chứa lỗi lặp như "Hoàng Hoàng Linh Lâm", "Chu Chu Tuệ Nguyệt" là lỗi nghiêm trọng '
                'và sẽ bị loại bỏ.'
            )
        lines.append(
            'Cách gọi trong lời bình: giới thiệu tên ở lần xuất hiện đầu tiên nếu tự nhiên, sau đó gọi linh hoạt '
            'bằng đại từ nhân xưng (cậu, cô ấy, chàng trai...) hoặc vai trò nhận diện để mạch kể trôi chảy, '
            'tránh lặp lại tên riêng ở đầu mỗi câu. Với nhân vật ngoài danh sách, gọi bằng tên thật nếu biết '
            'hoặc dùng vai trò/đặc điểm nhận diện rõ ràng.'
        )
    else:
        # Chưa có nhân vật đăng ký — vẫn nhắc quy ước tên theo chế độ người dùng chọn.
        lines.append('## Quy ước tên nhân vật')
        if name_mode == 'romaji':
            lines.append(
                'Khi gọi nhân vật bằng tên riêng, dùng tên gốc Latin hóa (Romaji, ví dụ "Jin", "Naruto", "Sakura") — '
                'tuyệt đối KHÔNG dùng Kanji (漢字) hoặc Kana (仮名/カタカナ) vì TTS tiếng Việt không đọc được. '
                'Nếu không biết Romaji chính xác, dùng cách phiên âm Latin gần nhất nhưng vẫn phải là ký tự A-Z.'
            )
        else:
            lines.append(
                'Khi gọi nhân vật bằng tên riêng, dùng tên tiếng Việt (Việt hóa tên tiếng Nhật) — '
                'không xen tên gốc Kanji/Katakana hay Romaji khác.'
            )
        lines.append(
            'Dùng đại từ nhân xưng linh hoạt và tự nhiên sau lần đầu gọi tên, tránh mở đầu mọi câu '
            'bằng tên nhân vật một cách rập khuôn.'
        )
    lines.append('')
    return '\n'.join(lines)


def build_scene_prompt(style: str = 'narrative', num_segments: int = 0, target_words: int = 0, target_sec: int = 0, video_duration: float = 0, characters: list | None = None, name_mode: str = 'romaji', series_description: str | None = None, free_order: bool = False) -> str:
    """Tạo prompt chuẩn hóa hướng dẫn Gemini sinh kịch bản chi tiết theo từng phân cảnh."""
    style_guides = {
        'narrative': {
            'guide': (
                'kể chuyện điện ảnh kịch tính, lôi cuốn: Mở đầu bằng một mâu thuẫn hoặc tình huống gay cấn (hook) '
                'khiến người xem bị cuốn hút ngay; xâu chuỗi các sự kiện bằng logic nhân - quả và diễn biến tâm lý '
                'thay vì chỉ thuật lại hình ảnh; cảnh tĩnh dùng câu giàu hình ảnh và cảm xúc, cảnh hành động dùng '
                'động từ mạnh và nhịp câu dứt khoát; đẩy cao trào bằng các biến cố dồn dập; kết thúc bằng câu gợi mở '
                '(cliffhanger) đắt giá rút ra trực tiếp từ diễn biến cuối, khiến người xem tò mò đón xem tập kế tiếp'
            ),
            'examples': [
                '00:00\tGiữa màn tuyết lạnh giá, học viện ma pháp đáng lẽ đang chìm trong yên bình bỗng rung chuyển dữ dội bởi hồi chuông báo động đỏ.',
                '00:22\tNguồn cơn bắt đầu từ căn hầm cấm, nơi cậu thiếu niên Jin vô tình chạm tay vào khối thạch phong ấn và bị một luồng hắc ám nuốt chửng linh hồn.',
                '00:41\tChưa kịp định thần sau biến cố kinh hoàng, một bóng đen sát thủ đã bất ngờ lao tới với nhát kiếm chí mạng nhắm thẳng vào tim cậu.',
                '00:58\tThế nhưng trong khoảnh khắc sinh tử, ngọn lửa ma thuật cổ xưa bỗng tự phát nổ bẻ gãy lưỡi gươm, mở ra một bí mật kinh thiên động địa. Liệu Jin có thể sống sót rời khỏi đây?',
            ],
        },
        'humorous': {
            'guide': (
                'hài hước, hóm hỉnh, bắt trend như một streamer duyên dáng: lời bình dí dỏm, chêm các câu nói thịnh hành, '
                'ví von đời thường duyên dáng nhưng XƯƠNG SỐNG CỐT TRUYỆN PHẢI LIỀN MẠCH, không kể chuyện chắp vá; '
                'tiếng cười xuất phát từ sự trớ trêu của hoàn cảnh, sự lố bịch và khoảng cách giữa kỳ vọng với thực tế; '
                'kết nối các câu bằng khẩu ngữ tự nhiên (ai mà ngờ, vừa dứt lời thì, đời không như là mơ...); '
                'khi gặp cảnh mất mát hoặc bi kịch thì hạ giọng nghiêm túc giữ trọn cảm xúc thật; '
                'kết thúc bằng cú chốt hài nhẹ hoặc bắt trend rồi hẹn gặp ở tập tiếp'
            ),
            'examples': [
                '00:00\tHội đồng pháp sư long trọng gọi tên Jin lên bục thể hiện tài năng, nhưng ai ngờ cậu bé lại mang đến một màn tấu hài ngoài dự kiến.',
                '00:22\tTự tin bước tới sờ thử viên phong ấn cổ đại, và chỉ trong một nốt nhạc, Jin đã chính thức thăng hạng từ người yếu nhất trường lên thành... yếu nhì.',
                '00:41\tCứ tưởng thế là xong đời học sinh cá biệt, thì đùng một cái sát thủ nhảy ra đòi lấy mạng, biến ngày khai giảng thành ngày báo thù.',
                '00:58\tNhưng đời đúng là lắm cú twist, ngọn lửa đen tự bay ra bảo kê cho cậu chủ nhiệt tình hơn cả bảo vệ trường. Đồng minh xịn thế này thì tập sau tha hồ gáy rồi!',
            ],
        },
        'analytical': {
            'guide': (
                'phân tích sâu sắc, đọc vị chiến thuật: lồng ghép giải mã động cơ, tâm lý và ý nghĩa nút thắt NGAY trong '
                'mạch kể chuyện; làm rõ nguyên nhân ẩn sau từng hành động của nhân vật, biến câu chuyện thành một ván cờ '
                'đấu trí căng thẳng; ngôn ngữ sắc bén, lập luận chặt chẽ nhưng luôn bám sát hình ảnh thực tế trên màn hình; '
                'kết thúc bằng nhận định then chốt về bước ngoặt cục diện và hệ quả khó lường cho tập kế tiếp'
            ),
            'examples': [
                '00:00\tHọc viện mở cửa đón tân binh giữa bão tuyết, nhưng ánh mắt sắc lạnh của viện trưởng cho thấy đây hoàn toàn không phải một kỳ tuyển sinh bình thường.',
                '00:22\tViệc Jin chạm vào khối phong ấn cấm thực chất đã nằm sẵn trong tính toán, biến cậu thành con tốt thí hoàn hảo để kích hoạt cấm thuật.',
                '00:41\tSự xuất hiện chớp nhoáng của tên sát thủ chính là phép thử cuối cùng nhằm ép nguồn năng lượng bóng tối bên trong Jin phải thức tỉnh toàn diện.',
                '00:58\tĐòn phản công tự động của ngọn lửa đen đã xác nhận mối nghi ngờ lớn nhất: cậu không chỉ là nạn nhân, mà chính là chìa khóa lật đổ toàn bộ vương triều.',
            ],
        },
        'concise': {
            'guide': (
                'súc tích, dồn dập, hồi hộp: lược bỏ toàn bộ chi tiết thừa và tính từ sáo rỗng, tập trung vào các sự kiện '
                'chính và bước ngoặt mang tính quyết định; các câu ngắn nối tiếp nhau như hiệu ứng domino, sự kiện trước '
                'lập tức kích hoạt biến cố sau; nhịp kể nhanh như vũ bão nhưng vẫn liền mạch rõ ràng; '
                'kết thúc bằng một câu chốt gãy gọn về tình thế ngàn cân treo sợi tóc'
            ),
            'examples': [
                '00:00\tHồi chuông báo động xé toạc màn đêm tại học viện ma pháp.',
                '00:20\tJin vô tình phá vỡ khối cổ thạch, giải phóng con mắt bóng tối ngàn năm.',
                '00:38\tSát thủ lập tức ập tới hạ sát nhằm bịt đầu mối, nhưng ngọn lửa đen bùng lên thiêu rụi kẻ tấn công.',
                '00:55\tJin thoát chết trong gang tấc nhưng đã trở thành mục tiêu săn đuổi số một của toàn đế quốc.',
            ],
        },
    }
    selected = style_guides.get(style, style_guides['narrative'])
    selected_style = selected['guide']
    style_example = '\n'.join(selected['examples'])
    if free_order:
        # Ví dụ phi tuyến: timestamp KHÔNG tăng dần để AI thấy rõ việc đảo cảnh là hợp lệ.
        _starts = ['14:32', '02:10', '08:45', '20:07', '05:33', '17:20']

        def _fmt_sec(total):
            if total >= 3600:
                return '{:02d}:{:02d}:{:02d}'.format(total // 3600, (total % 3600) // 60, total % 60)
            return '{:02d}:{:02d}'.format(total // 60, total % 60)

        def _rewrite_example(line, idx):
            m = re.match(r'\d{2}:\d{2}(?::\d{2})?\t(.*)$', line)
            if not m:
                return line
            narration = m.group(1)
            start = _starts[idx % len(_starts)]
            words = [w for w in re.split(r'\s+', narration.strip()) if w]
            total = sum(int(x) * f for x, f in zip(reversed(start.split(':')), (1, 60, 3600)))
            total += max(8, int(round(len(words) / 4.3 + 2)))
            return '{0} --> {1}\t{2}'.format(start, _fmt_sec(total), narration)

        style_example = '\n'.join(_rewrite_example(l, i) for i, l in enumerate(style_example.split('\n')))
    # Mỗi cảnh ~20 từ cho MỌI chế độ; số cảnh do AI tự chọn sao cho tổng từ đạt target.
    per_seg_words = 20
    per_min, per_max = 16, 24
    count_basis = max(5, int(round(target_words / per_seg_words))) if target_words > 0 else (num_segments or 75)
    line_count_line = '- Số dòng do bạn tự chọn; với ~{0} từ/dòng thì sẽ vào khoảng {1} dòng để tổng từ đạt ngân sách.'.format(per_seg_words, count_basis)
    sent_range = '2–3 câu ngắn' if style == 'concise' else '1–2 câu'
    vdur_txt = _fmt_mmss(video_duration) if video_duration > 0 else 'toàn bộ video'
    character_block = _build_character_registry_block(characters, name_mode)

    series_block = ''
    if series_description and series_description.strip():
        series_block = '''

## Bối cảnh toàn bộ series
Đây là mô tả cốt truyện/bối cảnh của series do người dùng cung cấp. Dùng nó để hiểu bối cảnh chung, quan hệ nhân vật và mạch truyện đang diễn ra. Trong lời bình tập này: chỉ kể những gì THẤY được trong video hiện tại; mô tả series chỉ dùng làm bối cảnh để diễn đạt rõ ràng và nhất quán, không bịa ra chi tiết không xuất hiện trong video.
--- MÔ TẢ SERIES ---
{series_description}'''.format(series_description=series_description.strip())

    if free_order:
        seg_section = f'''## 4. TỰ DO CHỌN CẢNH & SÁNG TẠO MẠCH KỂ (FREE-FORM EDITORIAL)
- Bạn là biên kịch tự do: hãy TỰ CHỌN những cảnh/cụm sự kiện QUAN TRỌNG NHẤT làm nên câu chuyện.
- Bạn ĐƯỢC PHÉP đảo thứ tự kể so với trình tự thời gian gốc của video để tạo mạch kể mới lạ, cuốn hút hơn: bắt đầu bằng một cảnh cao trào gây sốc làm hook, rồi quay ngược giải thích nguyên nhân (in medias res), hoặc nhóm các tình tiết theo chủ đề thay vì theo dòng thời gian.
- Timestamp KHÔNG bắt buộc tăng dần — chúng là con trỏ neo đến VỊ TRÍ THẬT của cảnh trong video gốc (để hệ thống cắt đúng hình cho lời bình đó). Nếu mạch kể bạn dựng đặt cảnh ở phút 15 trước cảnh ở phút 02, điều đó hoàn toàn hợp lệ.
- Không bắt buộc phủ kín toàn bộ video; không bắt buộc số phân đoạn cố định — chọn đúng những cảnh phục vụ mạch kể bạn đang dựng. Bỏ qua OP/ED/credit/teaser.
- Tự quyết định số phân đoạn phù hợp với câu chuyện bạn kể và ngân sách từ ({target_words} từ). Nếu chọn ít cảnh, mỗi cảnh phải nhiều câu hơn để tổng từ vẫn đạt ngân sách; nếu chọn nhiều cảnh, mỗi cảnh ngắn lại tương ứng.
- Dù đảo thứ tự, mạch lời bình vẫn phải liền mạch như một câu chuyện: người nghe hiểu được quan hệ nhân quả, không bị rối vì nhảy cảnh vô tội vạ.'''
        priority_4 = 'Số phân đoạn vừa đủ để kể câu chuyện hấp dẫn và tổng từ đạt ngân sách.'
        priority_3 = 'Chọn đúng cảnh quan trọng, mạch kể được phép phi tuyến.'
        format_header = 'MM:SS --> MM:SS<TAB>lời bình'
        format_suffix = 'Mỗi dòng là MỘT KHOẢNG thời gian (bắt đầu --> kết thúc) đánh dấu vị trí cảnh trong video gốc, theo sau bởi phím TAB và lời bình hấp dẫn cho cảnh đó.'
        act_middle = '- Thân bài (Phát triển & Cao trào): Dẫn dắt qua các bước ngoặt leo thang đến đỉnh điểm cao trào; được phép kể phi tuyến (quay ngược, cắt lớp, nhóm theo chủ đề) miễn là người nghe theo dõi được mạch truyện. Các sự kiện móc xích chặt chẽ: biến cố A dẫn tới hệ quả B, dồn nhân vật vào thế phải hành động.'
    else:
        seg_section = f'''## 4. PHÂN ĐOẠN VÀ TRÌNH TỰ THỜI GIAN
- Kể lần lượt theo thứ tự xuất hiện trong video, timestamp tăng dần.
- Chia video thành các phân đoạn theo nhịp kể chuyện: mỗi phân đoạn là một nhịp cảnh hoặc một bước chuyển biến rõ ràng, thường cách nhau 10–30 giây, chia theo nhịp kể chứ không chia đều theo thời gian máy móc. SỐ PHÂN ĐOẠN DO BẠN TỰ CHỌN, miễn tổng từ đạt ngân sách ở mục 5.
- Bỏ qua phần nhạc OP/ED/credit/teaser thuần túy (dù ở đầu, giữa hay cuối video). Tóm tắt đầy đủ mọi nội dung thật, kể cả đoạn mở đầu trước intro (cold open) và đoạn sau outro (post-credit): timestamp đầu tiên là cảnh thật mở đầu video, timestamp cuối cùng là cảnh thật kết thúc video. Nếu video không có OP/ED rõ ràng, dùng toàn bộ video.'''
        priority_4 = 'Số phân đoạn tự chọn, phủ đủ các diễn biến quan trọng.'
        priority_3 = 'Trình tự thời gian và phủ đủ các diễn biến quan trọng.'
        format_header = 'MM:SS<TAB>lời bình'
        format_suffix = ''
        act_middle = '- Thân bài (Phát triển & Cao trào): Kể diễn biến tuần tự từ xung đột ban đầu, qua các bước ngoặt leo thang đến đỉnh điểm cao trào. Các sự kiện móc xích chặt chẽ: biến cố A dẫn tới hệ quả B, dồn nhân vật vào thế phải hành động.'

    return f'''Bạn là biên kịch anime chuyên nghiệp. Hãy xem toàn bộ video dài {vdur_txt} và sáng tạo kịch bản tóm tắt phim (Anime Recap) xuất sắc, hấp dẫn theo các yêu cầu sau:

## 1. NGUYÊN TẮC CỐT LÕI: MẠCH KỂ CHUYỆN LIỀN MẠCH (STORYTELLING FLOW)
- Kịch bản tóm tắt phải là MỘT CÂU CHUYỆN HOÀN CHỈNH, LIÊN TỤC VÀ CUỐN HÚT từ đầu đến cuối.
- Các mốc thời gian (MM:SS) ở đầu dòng chỉ là điểm neo đồng bộ với video. Phần lời bình KHÔNG ĐƯỢC viết rời rạc, không liệt kê hành động thô vụn theo kiểu "cảnh này làm gì, cảnh sau làm gì".
- Móc nối tự nhiên (Chain-of-Narration): Nếu đọc liên tục toàn bộ lời bình (bỏ timestamp), người nghe phải cảm nhận như đang nghe một câu chuyện trôi chảy, hấp dẫn. Câu sau phải kế thừa ngữ cảnh, cảm xúc hoặc quan hệ nhân - quả của câu trước bằng các liên từ chuyển ý tự nhiên (ví dụ: "thế nhưng", "chính lúc này", "chưa kịp định thần", "sự thật đằng sau", "hành động liều lĩnh đó lập tức kéo theo...").
- Sử dụng đại từ nhân xưng linh hoạt (cậu, cô ấy, hắn, chàng trai, đối phương...) sau lần đầu giới thiệu tên, tránh lặp lại tên nhân vật ở đầu mỗi câu gây đơn điệu.

## 2. CẤU TRÚC 3 HỒI ĐIỆN ẢNH (THREE-ACT ARC)
- Mở đầu (Hook - 2 đến 3 phân đoạn đầu): Bắt vào một chi tiết/mâu thuẫn kịch tính hoặc tình thế nguy cấp ngay trên màn hình để gây tò mò, giữ chân người xem ngay từ giây đầu tiên, đồng thời giới thiệu nhanh nhân vật chính và xung đột cốt lõi.
{act_middle}
- Kết thúc (Cliffhanger / Dư âm - phân đoạn cuối): Chốt lại kết quả diễn biến trong video bằng một câu tự nhiên, giàu cảm xúc hoặc để lại một móc câu (cliffhanger) đắt giá rút ra từ cảnh cuối phim, khiến người xem háo hức muốn xem ngay tập sau.

## 3. TRUNG THỰC VỚI VIDEO
Mô tả chính xác những gì xuất hiện trong video: nhân vật, hành động, sự kiện, lời thoại và diễn biến theo đúng thực tế, không bịa đặt những chi tiết không có trên màn hình. Khi thông tin không thể hiện rõ (tên nhân vật, lời thoại, nguyên nhân), gọi nhân vật bằng vai trò hoặc đặc điểm nhận diện rõ ràng và diễn đạt ý nghĩa cảnh theo quan sát thực tế.

{character_block}
{series_block}

{seg_section}

## 5. ĐỘ DÀI & NGÂN SÁCH TỪ (TỔNG TỪ LÀ RÀNG BUỘC CỨNG)
- Tổng cộng BẮT BUỘC khoảng {target_words} từ (±10%, tức từ {int(target_words*0.9)} đến {int(target_words*1.1)} từ). Đếm tổng số từ của TOÀN BỘ lời bình sau khi viết xong và chỉnh lại cho đúng ngân sách này.
{line_count_line}
- Mỗi dòng khoảng {per_seg_words} từ (thường {per_min}–{per_max} từ), không gộp quá nhiều ý vào một dòng, cũng không chia thành các dòng quá ngắn.
- Mỗi dòng là {sent_range}, hoàn chỉnh, trôi chảy, độ dài giữa các dòng tương đối đều để giọng đọc giữ nhịp ổn định.
- Câu từ viết bằng tiếng Việt tự nhiên, ngắt nghỉ dấu câu rõ ràng, tối ưu cho văn nói đọc thành tiếng, tránh câu quá dài gây hụt hơi hoặc câu cộc lốc vô nghĩa.
- Khi độ dài và độ trung thực với video xung đột, ưu tiên độ trung thực.

## 6. PHONG CÁCH KỂ CHUYỆN: "{style.upper()}"
{selected_style}

## 7. THỨ TỰ ƯU TIÊN
Khi các yêu cầu xung đột, tuân thủ thứ tự ưu tiên:
1. Trung thực với nội dung hiển thị trong video.
2. Mạch kể chuyện liền mạch, hấp dẫn thành 1 câu chuyện thống nhất.
3. {priority_3}
4. {priority_4}
5. Đạt CHÍNH XÁC mục tiêu tổng {target_words} từ (khoảng {per_seg_words} từ/dòng).
6. Giọng văn tự nhiên, sắc thái theo style đã chọn.

## 8. ĐỊNH DẠNG ĐẦU RA BẮT BUỘC
Xuất kịch bản dưới dạng các dòng, mỗi phân đoạn đúng một dòng:

{format_header}

Ví dụ đúng định dạng và thể hiện tính liền mạch (style "{style}") — CHỈ minh họa cấu trúc và cách neo timestamp, KHÔNG phải độ dài mục tiêu: số từ mỗi dòng thực tế phải theo đúng ngân sách ở mục 5 (khoảng {per_seg_words} từ/dòng). Nội dung viết mới hoàn toàn theo video:
{style_example}''' + (('\n' + format_suffix) if format_suffix else '')


def _normalize_narration(text: str) -> str:
    """Dọn lời bình trước khi gửi TTS: thay dấu gạch ngang '-' bằng khoảng trắng
    (CapCut TTS vô tình đọc cả dấu '-'), nén nhiều khoảng trắng liền thành 1."""
    text = (text or '').strip()
    if not text:
        return text
    text = text.replace('-', ' ')
    text = re.sub(r'[ \t]+', ' ', text).strip()
    return text


# Ký tự chữ cái và số tiếng Việt / Latinh đầy đủ để nhận diện ranh giới từ (Unicode word boundary)
_VN_WORD_CHARS = r'a-zA-Z0-9_àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ'


def normalize_character_names(narration: str, characters: list | None = None) -> str:
    """Đồng nhất tên nhân vật trong lời bình: thay alias bằng canonical name an toàn tuyệt đối.

    Cải tiến an toàn:
    1. Cơ chế Token Placeholder chống lỗi đệ quy / nhân đôi tên khi canonical chứa alias con.
    2. Khử triệt để lỗi AI nhân đôi họ tên ("Hoàng Hoàng Linh Lâm" -> "Hoàng Linh Lâm").
    3. Sử dụng Unicode-safe word boundary thay cho \\b thuần ASCII để không hỏng tiếng Việt.
    4. Với alias 1 từ đơn (ví dụ: "Lâm", "Phong"): chỉ thay thế khi từ trong văn bản được viết
       hoa chữ đầu (Title Case) hoặc viết hoa toàn bộ, chống thay thế nhầm các từ thông thường
       (như "lâm nguy", "phong ba").
    5. Sắp xếp alias từ dài đến ngắn để tránh alias ngắn nuốt mất cụm từ dài hơn.
    """
    if not characters or not narration:
        return narration

    result = narration
    tokens_map = {}

    for idx, c in enumerate(characters):
        canonical = (c.get('name') or '').strip()
        if not canonical:
            continue
        token = f"___CHAR_TOK_{idx}___"
        tokens_map[token] = canonical

        # 1. Khử lỗi AI nhân đôi họ tên trước ("Hoàng Hoàng Linh Lâm" -> token)
        parts = canonical.split()
        if len(parts) >= 2:
            head = re.escape(parts[0])
            rest = re.escape(' '.join(parts[1:]))
            result = re.sub(
                rf'(?<![{_VN_WORD_CHARS}])(?:{head}[ \t]+)+{head}[ \t]+{rest}(?![{_VN_WORD_CHARS}])',
                token,
                result,
                flags=re.IGNORECASE
            )

        # 2. Tạm bảo vệ tên canonical nếu đã có sẵn trong văn bản -> token
        result = re.sub(
            rf'(?<![{_VN_WORD_CHARS}]){re.escape(canonical)}(?![{_VN_WORD_CHARS}])',
            token,
            result
        )

        # 3. Lọc và sắp xếp alias từ dài đến ngắn
        raw_aliases = [a.strip() for a in (c.get('aliases') or []) if a and a.strip() and a.strip() != canonical]
        aliases = sorted(dict.fromkeys(raw_aliases), key=len, reverse=True)

        for alias in aliases:
            if not alias or alias.lower() == canonical.lower():
                continue
            esc_alias = re.escape(alias)
            pattern = rf'(?<![{_VN_WORD_CHARS}]){esc_alias}(?![{_VN_WORD_CHARS}])'
            if len(alias.split()) == 1:
                # Alias 1 từ đơn: nếu viết hoa chữ đầu thì chỉ match khi văn bản cũng viết hoa
                if alias[0].isupper():
                    result = re.sub(pattern, token, result)
                else:
                    result = re.sub(pattern, token, result, flags=re.IGNORECASE)
            else:
                result = re.sub(pattern, token, result, flags=re.IGNORECASE)

    # 4. Bước cuối cùng: Khôi phục tất cả token về canonical name chuẩn
    for token, canonical in tokens_map.items():
        result = result.replace(token, canonical)

    return result


def parse_result_text(text: str, characters: list | None = None, free_order: bool = False) -> list:
    """Parse kết quả lời bình AI — hỗ trợ cả MM:SS\tnarr và HH:MM:SS --> HH:MM:SS\tnarr."""
    # Regex timestamp: chấp nhận MM:SS (2 phần) hoặc HH:MM:SS (3 phần), tùy chọn milliseconds
    ts = r'\d{1,3}:\d{2}(?::\d{2}(?:[,.]\d{1,3})?)?'
    lines = []
    
    # Loại bỏ code block markdown nếu có (```tsv, ```text, ```)
    clean_text = re.sub(r'```[a-zA-Z]*', '', text)
    clean_text = clean_text.replace('```', '')
    
    # Đồng nhất tên nhân vật trước khi parse
    clean_text = normalize_character_names(clean_text, characters)

    for line in clean_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Bỏ qua các dòng chú thích/tiêu đề của AI
        if line.startswith('#') or line.lower().startswith('dưới đây') or line.lower().startswith('kịch bản:'):
            continue

        # Ưu tiên: MM:SS --> MM:SS\tnarr  (AI vẫn thêm --> thì vẫn parse được)
        m = re.match(rf'^({ts})\s*-->\s*({ts})[\t\s]+(.*)$', line)
        if m:
            lines.append((m.group(1), m.group(2), m.group(3).strip(), True))
            continue
        # Format đơn giản: MM:SS\tnarr  (chỉ 1 mốc, backend tự tính end)
        m = re.match(rf'^({ts})[\t\s]+(.+)$', line)
        if m:
            lines.append((m.group(1), None, m.group(2).strip(), False))

    if not lines:
        raise Exception(f'Không parse được phân đoạn từ văn bản AI trả về: {text[:200]}')

    segments = []
    total = len(lines)
    for i, (st, et, narr, has_pair) in enumerate(lines):
        start_sec = time_to_seconds(st)
        if has_pair and et:
            end_sec = time_to_seconds(et)
        elif free_order:
            end_sec = start_sec + 15.0
            # Ước lượng thời lượng từ số từ lời bình (đọc ~4.6 từ/giây) khi AI chỉ đưa 1 mốc
            wc = len((narr or '').split())
            if wc > 0:
                end_sec = start_sec + max(8.0, wc / WPS + 2.0)
        elif i + 1 < total:
            end_sec = time_to_seconds(lines[i + 1][0])
        else:
            end_sec = start_sec + 15.0

        if end_sec <= start_sec:
            end_sec = start_sec + 8.0

        segments.append({
            'index': i + 1,
            'start_time': st,
            'end_time': _fmt_srt(end_sec),
            'start_seconds': start_sec,
            'end_seconds': end_sec,
            'narration': _normalize_narration(narr),
            'scene_description': f'Phân cảnh {i + 1}',
        })
    return segments


FALLBACK_MODELS = ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite']

# Tốc độ đọc TTS CapCut: WORDS_PER_MINUTE / 60 = 4.62 từ/giây (giá trị ĐO THỰC từ các tập
# đã chạy, giọng capcut_BV421_vivn_streaming; khớp syls_per_sec=5.5/Voice.json).
# Dùng để ƯỚC LƯỢNG thời lượng đọc của kịch bản AI (báo cáo, không dùng lại để retry).
WPS = WORDS_PER_MINUTE / 60.0


def _script_duration(segments: list) -> float:
    """Ước lượng thời lượng đọc toàn bộ kịch bản (giây) dựa trên tổng số từ lời bình."""
    total_w = sum(len(str(s.get('narration') or '').split()) for s in segments)
    return total_w / WPS


def _stretch_timestamps(segments: list, video_duration: float) -> list:
    """Giãn TUYẾN TÍNH các mốc AI về phủ trọn [0, video_duration], giữ nguyên nhịp tương đối:
    t_i' = video_duration * (t_i - t0) / (tN_end - t0). Cảnh đầu bắt đầu 00:00, cảnh cuối kết
    đúng lúc hết video, mốc liên tiếp không chồng lấn. Nếu AI đã trải gần đúng thì gần như
    không đổi; nếu AI tụ mốc thì kéo giãn để không bỏ sót đầu/cuối. video_duration<=0 -> giữ nguyên.
    Nếu mọi mốc trùng nhau -> chia đều dự phòng."""
    if not segments or video_duration <= 0:
        return segments
    n = len(segments)
    starts = [max(0.0, float(s.get('start_seconds', 0) or 0)) for s in segments]
    ends = [float(s.get('end_seconds', s.get('start_seconds', 0) or 0) + 15) for s in segments]
    ends = [max(ends[i], starts[i]) for i in range(n)]
    t0, tn = min(starts), max(ends)
    span = tn - t0
    new_starts = []
    if span <= 0:
        new_starts = [video_duration * i / n for i in range(n)]
    else:
        new_starts = [video_duration * (st - t0) / span for st in starts]
    for i, s in enumerate(segments):
        ns = max(0.0, float(new_starts[i]))
        if i + 1 < n:
            ne = max(0.0, float(new_starts[i + 1]))
        else:
            ne = video_duration
        if ne <= ns:
            ne = min(video_duration, ns + 5.0)
        s['start_seconds'] = round(ns, 3)
        s['end_seconds'] = round(min(ne, video_duration), 3)
        s['start_time'] = _fmt_srt(ns)
        s['end_time'] = _fmt_srt(min(ne, video_duration))
    return segments


def _is_key_error(err_msg: str) -> bool:
    """Kiểm tra xem lỗi có thuộc phía key/tài khoản/quota hay không."""
    markers = ['429', '403', '401', 'PERMISSION', 'RESOURCE_EXHAUSTED', 'RATE_LIMIT',
               'quota', 'QUOTA', 'high demand', 'UNAVAILABLE', 'UNAUTHENTICATED',
               'API key', 'api key', 'Key', '503', 'NOT_FOUND', '404',
               'timeout', 'Timeout', 'timed out', 'DEADLINE_EXCEEDED', 'deadline']
    return any(m in err_msg for m in markers)


_PAIR_LOCK = threading.Lock()
_pair_index = 0


def _load_rotation() -> dict:
    """Đọc state rotation (index + số lần dùng/key) từ SQLite app_kv — để RESTART server không
    làm rotation quay ngược về các key đầu danh sách. Lỗi đọc thì coi như state mới."""
    global _pair_index
    idx, counts = 0, {}
    try:
        from backend.core import database
        data = database.get_app_kv('gemini_rotation')
        if data and isinstance(data, dict):
            idx = int(data.get('index', 0) or 0)
            counts = {str(k): int(v) for k, v in (data.get('counts') or {}).items()}
    except Exception:
        pass
    _pair_index = idx
    return counts


def _save_rotation(index: int, counts: dict):
    """Ghi state rotation nguyên tử vào SQLite app_kv."""
    try:
        from backend.core import database
        database.set_app_kv('gemini_rotation', {'index': index, 'counts': counts})
    except Exception:
        pass


def _next_key(keys: list) -> str:
    """Chọn 1 key CHÍNH cho mỗi lượt thử = key có số lần ĐÃ DÙNG thấp nhất (tràn đều tải);
    tie-break luân phiên bằng index. State lưu đĩa nên sau khi restart vẫn tiếp tục vòng
    tròn, không lặp lại các key đầu. Không đổi model cho tới khi thử hết mọi key."""
    global _pair_index
    with _PAIR_LOCK:
        counts = _load_rotation()
        idx = _pair_index
        min_c = min(counts.get(k, 0) for k in keys)
        tied = [k for k in keys if counts.get(k, 0) == min_c]
        pick = tied[idx % len(tied)]
        _pair_index = (idx + 1) % len(keys)
        _save_rotation(_pair_index, {k: counts.get(k, 0) for k in keys})
        return pick


def _bump_key_usage(api_key: str, keys: list):
    """Ghi nhận 1 lần dùng thực tế cho 1 key (generate thành công hay lỗi) — tiêu chí để
    vòng chọn key ít dùng nhất luôn phản ánh đúng tải, không lệch về key đầu."""
    with _PAIR_LOCK:
        counts = _load_rotation()
        counts[api_key] = counts.get(api_key, 0) + 1
        _save_rotation(_pair_index, {k: counts.get(k, 0) for k in keys})


def summarize_video(video_path: str, style: str = 'narrative', model_name: str = '', num_segments: int = 0, target_words: int = 0, target_sec: int = 0, progress_callback=None, video_duration: float = 0, characters: list | None = None, name_mode: str = 'romaji', series_description: str | None = None, free_order: bool = False) -> list:
    prompt = build_scene_prompt(style, num_segments, target_words, target_sec, video_duration, characters=characters, name_mode=name_mode, series_description=series_description, free_order=free_order)
    primary_model = model_name or GEMINI_MODEL
    models_to_try = [primary_model] + [m for m in FALLBACK_MODELS if m != primary_model]

    keys = key_pool.get_usable_keys()  # bỏ qua key đang cooldown (treo/lỗi gần đây)
    if not keys:
        raise Exception('Chưa có GEMINI API key nào trong key_pool')

    # MỖI TẬP gửi TỪNG KEY MỘT (1 key/lượt) theo vòng tròn ít dùng nhất; key nào thành công
    # thì LẤY NGAY kết quả đó, không so sánh/chọn lại. Chỉ thử key tiếp khi key hiện tại fail.
    # Hết key ở model này mới đổi model (giữ nguyên luật: chưa thử hết key thì không đổi model).
    # Upload LƯỜI: key nào tới lượt mới upload, kết quả cache lại để tái dùng cho model kế.
    uploads = {}  # api_key -> (gen_client, video_file)
    last_err = None

    def _run_one(entry, m):
        """1 lần generate_content trên (key, m). Trả (api_key, text, ok) —
        ok=False nghĩa là text chứa mô tả lỗi, không nhầm với nội dung kịch bản."""
        api_key, gen_client, video_file = entry
        try:
            resp = gen_client.models.generate_content(
                model=m,
                contents=[video_file, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.4
                )
            )
            if resp and resp.text:
                return (api_key, (resp.text or '').strip(), True)
            return (api_key, '', False)
        except Exception as e:
            return (api_key, str(e), False)

    # Model nào cũng vậy: thử lần lượt từng key (1 key/lượt), key đầu tiên trả kịch bản
    # hợp lệ được chọn ngay. Chỉ đổi model khi key nào cũng thất bại ở model hiện tại.
    try:
        for model_idx, m in enumerate(models_to_try):
            if progress_callback:
                if model_idx == 0:
                    progress_callback('Gemini đang phân tích bối cảnh và viết kịch bản (từng key một, key nào thành công trước lấy trước)...', 30)
                else:
                    progress_callback(f'Đã thử hết {len(keys)} key ở model {models_to_try[0]}, sang model {m}...', 32)

            tried = set()
            while len(tried) < len(keys):
                pool = [k for k in keys if k not in tried]
                api_key = _next_key(pool)
                tried.add(api_key)

                if api_key not in uploads:
                    prepared_now, upload_err = _upload_video_batch(video_path, [api_key], progress_callback)
                    if prepared_now:
                        uploads[api_key] = (prepared_now[0][1], prepared_now[0][2])
                    if upload_err:
                        last_err = upload_err

                entry = (api_key,) + uploads[api_key] if api_key in uploads else None
                if not entry:
                    continue  # upload key này fail -> thử key kế

                _key, payload, ok = _run_one(entry, m)
                _bump_key_usage(_key, keys)  # ghi nhận tải thực tế (cả fail) để tràn đều
                key_pool.record_key_result(_key, bool(ok and payload))  # fail → cooldown, khỏi cày lại
                if ok and payload:
                    # LẤY NGAY kết quả của key đầu tiên thành công, không so sánh thêm
                    segments = parse_result_text(payload, characters=characters, free_order=free_order)

                    if video_duration > 0 and not free_order:
                        # Giãn mốc AI phủ trọn toàn bộ video gốc (giữ nhịp tương đối)
                        segments = _stretch_timestamps(segments, video_duration)
                    est_dur = _script_duration(segments)
                    if progress_callback:
                        progress_callback(f'Gemini hoàn tất kịch bản ({len(segments)} phân cảnh, đọc ~{est_dur:.0f}s)!', 40)
                    return segments
                else:
                    if payload:
                        last_err = Exception(payload)

            # hết key ở model này mà vẫn chưa có kịch bản -> sang model kế
            continue

        raise Exception(f'Đã thử hết {len(keys)} key (từng key một) với mọi model mà không sinh được kịch bản. Lỗi cuối: {last_err}')
    finally:
        # Luôn dọn file đã upload ở MỌI key đã dùng (thắng hay thua) và ĐÓNG client
        # để giải phóng pool kết nối httpx (tránh tích lũy socket CLOSE_WAIT/BOUND).
        for _key, (gen_client, video_file) in uploads.items():
            try:
                gen_client.files.delete(name=video_file.name)
            except Exception:
                pass
            _close_client(gen_client)


# ── Tự phát hiện nhân vật từ kịch bản (auto-detect) ─────────────

# Model DÙNG RIÊNG để trích xuất nhân vật: CHỈ model LITE (rẻ, nhanh, ít vướng quota).
# Nhiệm vụ đơn giản nên không cần flash đầy đủ như GEMINI_MODEL.
EXTRACT_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']

# Timeout đọc response cho trích nhân vật (s): key khỏe trả lite text-only trong ~2s,
# quá hạn là treo → cắt ngay để chuyển key khác (client mặc định read 300s quá lâu).
_EXTRACT_TIMEOUT_SEC = float(os.environ.get('GEMINI_EXTRACT_TIMEOUT_SEC', '30'))

# Budget TỔNG cho 1 vòng đua key (s): kể cả khi mọi key cùng rỉ response (trickling,
# read-timeout không nổ) thì hết budget là chốt — extract không bao giờ ngâm quá mức này/model.
_EXTRACT_RACE_SEC = float(os.environ.get('GEMINI_EXTRACT_RACE_SEC', '90'))

# Các dòng "không có nhân vật" AI hay nhả ra — không phải tên, phải bỏ qua
_CHARACTER_NEGATIVE_NAMES = {
    'empty list', 'no output', 'none', 'none found', 'không có', 'khong co',
    'không có nhân vật', 'no characters', 'khong', 'n/a', 'not found',
}

# Từ gọi chung / KHÔNG phải tên riêng — loại khỏi gợi ý nhân vật
# Từ gọi chung / KHÔNG phải tên riêng — loại bỏ triệt để khỏi gợi ý nhân vật
CHARACTER_STOPWORDS = {
    # Vai trò kịch bản
    'nữ chính', 'nam chính', 'nhân vật chính', 'nhân vật phụ', 'nhân vật', 'phản diện', 'kẻ phản diện', 'kẻ thù',
    'đồng minh', 'đối thủ', 'người dẫn chuyện', 'tác giả', 'khán giả', 'người xem',
    # Giới tính & lứa tuổi thông thường
    'cô gái', 'chàng trai', 'người đàn ông', 'người phụ nữ', 'cậu bé', 'cô bé', 'đứa trẻ', 'đứa bé', 'ông chú',
    'bà lão', 'ông lão', 'cô nàng', 'anh chàng', 'tiểu tử', 'tiểu cô nương', 'thanh niên', 'thiếu niên', 'thiếu nữ',
    'người lạ', 'người qua đường', 'người dân', 'dân làng', 'dân chúng',
    # Gia đình & vai vế
    'người cha', 'người mẹ', 'cha', 'mẹ', 'bố', 'anh trai', 'em trai', 'chị gái', 'em gái', 'ông nội', 'bà nội',
    'ông ngoại', 'bà ngoại', 'người mẹ kế', 'người cha kế', 'anh chị', 'gia đình', 'dòng họ',
    # Chức vụ triều đình & quyền lực
    'thái tử', 'công chúa', 'hoàng tử', 'hoàng đế', 'vị vua', 'đức vua', 'vua', 'hoàng hậu', 'quý tộc', 'lãnh chúa',
    'quan viên', 'thị vệ', 'bảo vệ', 'vệ sĩ', 'lính gác', 'binh lính', 'quân lính', 'tướng quân', 'chỉ huy',
    'thủ lĩnh', 'người đứng đầu',
    # Học viện & học đường
    'thầy giáo', 'cô giáo', 'giáo viên', 'hiệu trưởng', 'viện trưởng', 'học sinh', 'sinh viên', 'tân binh',
    'bạn cùng lớp', 'người bạn', 'bạn thân',
    # Tu tiên, bang phái & võ hiệp
    'sư phụ', 'sư tôn', 'sư huynh', 'sư tỷ', 'sư muội', 'sư đệ', 'đệ tử', 'chưởng môn', 'tông chủ', 'trưởng lão',
    'giáo chủ', 'bang chủ', 'hội trưởng', 'đội trưởng', 'thành viên', 'tiền bối', 'hậu bối', 'lão quái', 'lão tổ',
    'cao thủ', 'đại hiệp', 'tiểu nhị',
    # Fantasy, Ma thuật & Quái vật
    'sát thủ', 'thích khách', 'dũng giả', 'anh hùng', 'người anh hùng', 'pháp sư', 'phù thủy', 'ma vương',
    'quỷ vương', 'ác ma', 'ác quỷ', 'quái vật', 'con quái vật', 'ma thú', 'linh thú', 'thần thú', 'yêu quái',
    'thần linh', 'thần quan', 'linh mục', 'mục sư',
    # Danh xưng nhận diện chung chung
    'cậu chủ', 'chủ nhân', 'tiểu thư', 'người hầu', 'cô hầu gái', 'đầy tớ', 'quản gia', 'hắc y nhân', 'kẻ áo đen',
    'bóng đen', 'kẻ giấu mặt', 'kẻ tấn công', 'kẻ bí ẩn', 'người bí ẩn', 'người lạ mặt', 'hung thủ', 'kẻ chủ mưu',
}


def _collapse_doubled_prefix(text: str) -> str:
    """Sửa lỗi AI nhân đôi họ/tên trong tên hoặc alias:
    - lặp tiền tố: 'Hoàng Hoàng Linh Lâm' → 'Hoàng Linh Lâm'
    - lặp cả cụm:   'Ca Minh Ca Minh' → 'Ca Minh'
    - lặp tiền tố nhiều vòng: 'Hoàng Hoàng Hoàng Linh Lâm' → 'Hoàng Linh Lâm'
    Chỉ gộp khi còn >= 2 âm tiết sau khi gộp (không đụng tên thật 2 từ kiểu 'Lâm Lâm')."""
    parts = re.split(r'\s+', (text or '').strip())
    changed = True
    while changed and len(parts) >= 2:
        changed = False
        # lặp cả cụm: nửa đầu == nửa sau
        if len(parts) >= 4 and len(parts) % 2 == 0:
            half = len(parts) // 2
            if [p.lower() for p in parts[:half]] == [p.lower() for p in parts[half:]]:
                parts = parts[:half]
                changed = True
                continue
        # lặp tiền tố: hai âm tiết đầu giống nhau
        if len(parts) >= 3 and parts[0] and parts[0].lower() == parts[1].lower():
            del parts[1]
            changed = True
    return ' '.join(parts)


def _parse_character_suggestions(text: str) -> list:
    """Parse kết quả Gemini về danh sách nhân vật → [{name, aliases}].

    Chấp nhận 1 dòng 1 nhân vật với các dạng: `tên<TAB>a1,a2`,
    `tên: a1, a2`, `tên — a1, a2`, `1. tên`, hay chỉ `tên`."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r'^[\*\-\d\.\)]+[\.\)]?\s*', '', line).strip()
        line = line.rstrip('.;,')
        if not line:
            continue
        if '\t' in line:
            name, _, rest = line.partition('\t')
            name, aliases = name.strip(), rest.strip()
        else:
            m = re.match(r'^(.+?)\s*[:：\-\–—]{1,2}\s*(.*)$', line)
            if m and m.group(2):
                name, aliases = m.group(1).strip(), m.group(2).strip()
            elif ' (' in line and line.endswith(')'):
                name, aliases = line.split(' (', 1)
                name, aliases = name.strip(), aliases.rstrip(')')
            else:
                name, aliases = line, ''
        name = _collapse_doubled_prefix(name).strip().strip('"“”')
        if not name:
            continue
        if name.lower() in CHARACTER_STOPWORDS or name.lower() in _CHARACTER_NEGATIVE_NAMES:
            continue
        # Bỏ qua nếu tên là từ đơn mà trùng với stopword hoặc quá ngắn (<=1 ký tự)
        if len(name) <= 1:
            continue
        raw_aliases = [_collapse_doubled_prefix(a.strip().strip('"“”')) for a in aliases.split(',') if a.strip()]
        clean_aliases = []
        for a in raw_aliases:
            if not a or a.lower() == name.lower():
                continue
            if a.lower() in CHARACTER_STOPWORDS or a.lower() in _CHARACTER_NEGATIVE_NAMES:
                continue
            clean_aliases.append(a)
        clean_aliases = list(dict.fromkeys(clean_aliases))[:5]
        if 2 <= len(name) <= 40:
            found.append({'name': name, 'aliases': clean_aliases})
    # dedupe theo tên (không phân biệt hoa thường)
    uniq, seen = [], set()
    for c in found:
        key = c['name'].lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


_EXTRACT_SYSTEM = (
    'Bạn là chuyên gia biên kịch hậu kỳ anime, chuyên rà soát kịch bản lời bình để lập danh sách nhân vật có TÊN RIÊNG.\n'
    'QUY TẮC BẮT BUỘC:\n'
    '1. CHỈ trích xuất khi nhân vật có TÊN RIÊNG ĐẶC ĐỊNH (Proper Name, ví dụ: Jin, Hoàng Linh Lâm, Sasuke, Lâm Phong).\n'
    '2. TUYỆT ĐỐI KHÔNG trích xuất các từ xưng hô, nghề nghiệp, chức vụ, vai vế, chủng tộc (như Sát thủ, Viện trưởng, '
    'Ma vương, Hiệu trưởng, Dũng giả, Đệ tử, Hắc y nhân, Cậu bé, Quái vật...). Nếu một người chỉ được gọi bằng vai trò mà '
    'không có tên riêng cụ thể thì BỎ QUA.\n'
    '3. Xuất đúng định dạng: tên_chính<TAB>alias1,alias2. Không thêm bất kỳ lời dẫn nào.'
)


def extract_characters_from_script(text: str, name_mode: str = 'vietnamese') -> list:
    """Gọi Gemini (chỉ text, không upload video) trích danh sách nhân vật chính từ lời bình.

    Trả list [{name, aliases}]. Dùng vòng tròn key + fallback model như summarize_video;
    text-only nên nhanh và rẻ. Lỗi mọi key/mọi model → raise."""
    if not text or not text.strip():
        return []
    if name_mode not in ('vietnamese', 'romaji'):
        name_mode = 'romaji'
    mode_txt = ('tên tiếng Việt thông dụng (Việt hóa nếu tên gốc là tiếng Nhật)'
                if name_mode == 'vietnamese'
                else 'tên gốc Latin hóa (Romaji), không dịch sang tiếng Việt')
    prompt = (
        'Dưới đây là lời bình tóm tắt của một tập phim anime.\n'
        'Hãy liệt kê các nhân vật có TÊN RIÊNG THẬT SỰ được nhắc đến trong lời bình theo định dạng:\n\n'
        'tên_chính<TAB>alias1,alias2\n\n'
        f'Quy ước tên chính: {mode_txt}.\n'
        'Alias là các cách gọi khác của CÙNG nhân vật xuất hiện trong lời bình '
        '(tên gốc Romaji/Kanji, biệt hiệu riêng...), phân tách bằng dấu phẩy; để trống nếu không có.\n'
        'LƯU Ý CỐT LÕI: TUYỆT ĐỐI BỎ QUA các danh xưng nghề nghiệp, chức danh, vai vế hoặc mô tả chung '
        '(như Viện trưởng, Sát thủ, Ma vương, Hiệu trưởng, Đệ tử, Cậu bé, Quái vật...).\n'
        'Nếu không có nhân vật tên riêng nào, trả đúng một dòng: KHONG_CO\n\n'
        f'Lời bình:\n{text}'
    )
    models_to_try = list(EXTRACT_MODELS)
    keys = key_pool.get_usable_keys()  # bỏ qua key đang cooldown (treo/lỗi gần đây)
    if not keys:
        raise Exception('Chưa có GEMINI API key nào trong key_pool')

    def _looks_like_error(raw: str) -> bool:
        t = (raw or '').lower()
        for kw in ('error', 'rate limit', 'quota exceeded', 'permission denied',
                   'invalid argument', 'resource exhausted', 'internal server'):
            if kw in t:
                return True
        return False

    def _race_one(api_key: str, m: str):
        """1 lượt gọi extract trên 1 key (chạy song song với các key khác).
        Trả (api_key, result, elapsed, err): result = list đã parse ([] nếu KHONG_CO),
        None khi fail (kèm err). Mỗi key dùng Client riêng nên thread-safe."""
        client = _client_for(api_key, read_timeout=_EXTRACT_TIMEOUT_SEC, conn_timeout=10.0)
        t1 = time.time()
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_EXTRACT_SYSTEM,
                    temperature=0.2,
                ),
            )
            raw = ((resp.text or '').strip()) if resp else ''
            dt = time.time() - t1
            if raw and not _looks_like_error(raw):
                if raw.strip().upper() == 'KHONG_CO':
                    return (api_key, [], dt, None)
                parsed = _parse_character_suggestions(raw)
                if parsed:
                    return (api_key, parsed, dt, None)
            return (api_key, None, dt, Exception(raw or 'Trả về rỗng'))
        except Exception as e:
            return (api_key, None, time.time() - t1, e)
        finally:
            _close_client(client)

    last_err = None
    for m in models_to_try:
        # ĐUA KEY: bắn cùng lúc toàn bộ key (daemon threads — key chậm còn treo không
        # bao giờ chặn tiến trình thoát), key nào trả kết quả hợp lệ trước thì lấy.
        # Tổng thời gian ≈ key nhanh nhất (~2s), không còn cộng dồn key treo.
        # Key thua (lỗi trước khi có người thắng) → cooldown; key về sau bị bỏ qua,
        # không ghi nhận gì (tránh phạt oan key chỉ vì chậm hơn).
        state = {'winner': None, 'results': {}, 'last_err': None}
        lock = threading.Lock()
        tick = threading.Event()

        def _worker(api_key: str, _m: str = m):
            res = _race_one(api_key, _m)
            _key, result, dt, err = res
            with lock:
                if _key in state['results']:
                    return
                state['results'][_key] = res
                if state['winner'] is not None:
                    return  # đã có người thắng → bỏ qua, không ghi nhận gì
                _bump_key_usage(_key, keys)
                if result is not None:
                    state['winner'] = res
                    key_pool.record_key_result(_key, True)
                    logger.info(f'[EXTRACT] RACE key#{keys.index(_key)} model={_m} THẮNG trong {dt:.1f}s ({len(result)} nhân vật)')
                else:
                    state['last_err'] = err
                    key_pool.record_key_result(_key, False)
                    logger.warning(f'[EXTRACT] RACE key#{keys.index(_key)} model={_m} thua sau {dt:.1f}s: {str(err)[:150]}')
            tick.set()

        for k in keys:
            threading.Thread(target=_worker, args=(k,), name=f'extract-race-{keys.index(k)}',
                             daemon=True).start()
        deadline = time.time() + _EXTRACT_RACE_SEC
        winner = None
        while True:
            with lock:
                if state['winner'] is not None:
                    winner = state['winner'][1]
                    break
                if len(state['results']) >= len(keys):
                    last_err = state['last_err']
                    break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            tick.wait(timeout=min(remaining, 2.0))
            tick.clear()
        if winner is not None:
            return winner
        if len(state['results']) < len(keys):
            # Hết budget mà vẫn còn key treo → tính thua hết để cooldown.
            last_err = TimeoutError(
                f'Quá {_EXTRACT_RACE_SEC:.0f}s chưa có key nào trả kết quả (model={m})')
            with lock:
                for k in keys:
                    if k not in state['results']:
                        key_pool.record_key_result(k, False)
            logger.warning(f'[EXTRACT] RACE model={m} hết budget {_EXTRACT_RACE_SEC:.0f}s '
                           f'({len(keys) - len(state["results"])} key còn treo → cooldown)')
        else:
            last_err = state['last_err']
        # hết key ở model này mà không có kết quả → sang model kế
        continue
    raise Exception(f'Không trích xuất được nhân vật từ kịch bản. Lỗi cuối: {last_err}')
