import os
import re
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from .config import LOGS_DIR

SERVER_LOG_PATH = os.path.join(LOGS_DIR, 'server.log')
_initialized = False

LOG_LINE_REGEX = re.compile(
    r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+\[([A-Z]+)\]\s+([\w\.\-]+):\s+(.*)$'
)

def init_logging():
    """Khởi tạo hệ thống logging ghi đồng thời ra console và file xoay vòng output/server.log."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    os.makedirs(LOGS_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers)
    if not has_console:
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        root_logger.addHandler(ch)

    has_file = any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers)
    if not has_file:
        try:
            fh = RotatingFileHandler(
                SERVER_LOG_PATH,
                maxBytes=10 * 1024 * 1024,
                backupCount=3,
                encoding='utf-8',
                delay=False
            )
            fh.setFormatter(fmt)
            root_logger.addHandler(fh)
        except Exception as e:
            print(f"[WARN] Không thể khởi tạo RotatingFileHandler cho {SERVER_LOG_PATH}: {e}")

    logging.getLogger('backend.core.logger').info("=== Hệ thống ghi nhật ký máy chủ đã khởi động ===")

def read_logs(limit: int = 300, level: str = None, search: str = None) -> dict:
    """Đọc và phân tích các dòng log gần nhất từ server.log thành cấu trúc dữ liệu JSON."""
    if not os.path.isfile(SERVER_LOG_PATH):
        return {'entries': [], 'total': 0, 'raw': ''}

    try:
        with open(SERVER_LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
    except Exception as e:
        return {'entries': [{'id': '0', 'time': datetime.now().isoformat(), 'level': 'ERROR', 'source': 'logger', 'message': f'Lỗi đọc file log: {e}', 'raw': str(e)}], 'total': 0, 'raw': str(e)}

    entries = []
    current_entry = None
    idx = 0

    target_level = level.upper().strip() if level and level.strip() and level.lower() != 'all' else None
    search_q = search.lower().strip() if search and search.strip() else None

    for line in all_lines:
        line_clean = line.rstrip('\r\n')
        m = LOG_LINE_REGEX.match(line_clean)
        if m:
            if current_entry:
                entries.append(current_entry)
            t_str, lvl, src, msg = m.groups()
            idx += 1
            current_entry = {
                'id': str(idx),
                'time': t_str,
                'level': lvl,
                'source': src,
                'message': msg,
                'raw': line_clean
            }
        else:
            if current_entry:
                current_entry['message'] += '\n' + line_clean
                current_entry['raw'] += '\n' + line_clean
            else:
                idx += 1
                current_entry = {
                    'id': str(idx),
                    'time': '',
                    'level': 'INFO',
                    'source': 'system',
                    'message': line_clean,
                    'raw': line_clean
                }

    if current_entry:
        entries.append(current_entry)

    total_count = len(entries)

    if target_level:
        entries = [e for e in entries if e['level'] == target_level]

    if search_q:
        entries = [e for e in entries if search_q in e['raw'].lower()]

    recent_entries = entries[-limit:] if limit > 0 else entries
    raw_text = '\n'.join(e['raw'] for e in recent_entries)

    return {
        'entries': recent_entries,
        'total': total_count,
        'filtered_count': len(entries),
        'raw': raw_text
    }

def clear_logs() -> bool:
    """Làm sạch nội dung file server.log."""
    try:
        with open(SERVER_LOG_PATH, 'w', encoding='utf-8') as f:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{now_str} [INFO] backend.core.logger: Đã làm sạch nhật ký máy chủ.\n")
        return True
    except Exception as e:
        logging.getLogger('backend.core.logger').error(f"Lỗi làm sạch file log: {e}")
        return False
