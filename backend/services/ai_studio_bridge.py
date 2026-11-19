"""Automation Google AI Studio qua Playwright CDP, trên Chrome PROFILE RIÊNG (ai_studio_auto).

Bối cảnh đã xác minh trên máy này (Chrome 151.0.7922.174):
- Chrome 136+ CHẶN remote-debugging (pipe lẫn port) trên thư mục User Data MẶC ĐỊNH
  → không thể CDP điều khiển profile Chrome thật của người dùng.
- Copy session real-profile sang dir khác KHÔNG giữ được đăng nhập (Device Bound Sessions).
→ Giải pháp: profile automation RIÊNG trong output/ai_studio_auto (dir non-default → CDP OK),
  người dùng đăng nhập 1 lần vào lần chạy đầu tiên (tự động chờ), session còn lại sau đó.

Flow 12 bước:
  B1. Mở Google AI Studio        → Popen Chrome (dir non-default) + CDP.
  B2. Workspace Prompt mới (new_chat).
  B3. Chọn model                  → best-effort theo options.model.
  B4. Chế độ Prompt + Thinking Level High (best-effort).
B5. Upload video                → nút + → "Upload files" → File Chooser.
   B6. Điền prompt NGAY sau upload (song song lúc video index).
   B7. Chờ Studio xử lý/index video (nút Run khả dụng).
   B8. Nhấn Run.
  B9. Theo dõi trạng thái Gemini.
  B10. Chờ response hoàn thành (stable detection).
  B11. Đọc response từ giao diện (turn model => ms-text-chunk).
  B12. Trả kết quả về backend.
"""

import os
import re
import time
import logging
import subprocess
import json
import threading
import urllib.request
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

AI_STUDIO_URL = "https://aistudio.google.com/app/prompts/new_chat"
CDP_HOST = "127.0.0.1"
CDP_PORT = 9223

# Automation AI Studio = 1 luồng: profile Chrome thật, phải nối tiếp.
_AUTOMATION_LOCK = threading.Lock()
_LOGIN_CHROME_PROC = None


def _is_profile_locked(user_data_dir=None) -> bool:
    """Kiểm tra xem Chrome có đang giữ khóa trên thư mục user data hay không."""
    ud = user_data_dir or _chrome_user_data()
    lock_path = os.path.join(ud, "lockfile")
    if not os.path.exists(lock_path):
        return False
    try:
        with open(lock_path, "a"):
            return False
    except (IOError, PermissionError):
        return True
    except Exception:
        return False


def get_ai_studio_account_info():
    """Lấy thông tin tài khoản Google đã đăng nhập trong profile Chrome automation."""
    user_data = _chrome_user_data()
    profile = _chrome_profile()
    pref_path = os.path.join(user_data, profile, "Preferences")
    
    is_running = _is_profile_locked(user_data) or _cdp_alive()
    
    info = {
        "logged_in": False,
        "email": None,
        "full_name": None,
        "picture_url": None,
        "profile_dir": user_data,
        "profile_name": profile,
        "is_running": is_running,
        "cdp_alive": _cdp_alive()
    }
    
    if os.path.exists(pref_path):
        try:
            with open(pref_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            accs = data.get("account_info", [])
            if isinstance(accs, list) and len(accs) > 0:
                first = accs[0]
                if first.get("email"):
                    info["logged_in"] = True
                    info["email"] = first.get("email")
                    info["full_name"] = first.get("full_name") or first.get("given_name")
                    info["picture_url"] = first.get("picture_url")
        except Exception as e:
            logger.warning("Không đọc được Preferences Chrome: %s", e)
            
    # Fallback kiểm tra Local State nếu chưa thấy trong Preferences
    if not info["logged_in"]:
        local_state = os.path.join(user_data, "Local State")
        if os.path.exists(local_state):
            try:
                with open(local_state, "r", encoding="utf-8", errors="ignore") as f:
                    ls = json.load(f)
                info_cache = ls.get("profile", {}).get("info_cache", {}).get(profile, {})
                if info_cache.get("user_name"):
                    info["logged_in"] = True
                    info["email"] = info_cache.get("user_name")
                    info["full_name"] = info_cache.get("name")
            except Exception:
                pass
                
    return info


def open_login_browser():
    """Mở Chrome profile riêng ở chế độ người dùng sạch (không CDP, không cờ automation)
    để người dùng đăng nhập tài khoản Google an toàn, vượt qua 2FA/Passkey mà không bị chặn bot."""
    global _LOGIN_CHROME_PROC
    user_data = _chrome_user_data()
    profile = _chrome_profile()
    os.makedirs(user_data, exist_ok=True)
    
    # Nếu CDP đang chạy, Chrome đã mở sẵn; đưa lên foreground
    if _cdp_alive():
        _bring_chrome_to_foreground(lambda m: logger.info(m))
        return {"ok": True, "message": "Chrome automation đang mở, đã đưa cửa sổ lên màn hình."}
        
    # Kiểm tra xem Chrome với user-data-dir này đã chạy chưa
    if _is_profile_locked(user_data):
        _bring_chrome_to_foreground(lambda m: logger.info(m))
        return {"ok": True, "message": "Chrome profile đã đang chạy, đã đưa cửa sổ lên màn hình."}
        
    args = [
        _chrome_exe(),
        f"--user-data-dir={user_data}",
        f"--profile-directory={profile}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        AI_STUDIO_URL,
    ]
    try:
        _LOGIN_CHROME_PROC = subprocess.Popen(args)
        return {"ok": True, "message": "Đã mở Google Chrome để bạn đăng nhập Google và chuẩn bị AI Studio."}
    except Exception as e:
        logger.error("Lỗi mở Chrome đăng nhập: %s", e)
        raise RuntimeError(f"Không thể mở Chrome: {e}")


def close_automation_browser():
    """Đóng tiến trình Chrome của profile automation (cả chế độ login lẫn CDP)
    để giải phóng profile trước khi chạy tác vụ tự động hoặc khi người dùng muốn đóng."""
    global _LOGIN_CHROME_PROC
    closed = False
    
    # 1. Tìm PID đang nghe cổng CDP_PORT để đóng dứt điểm ngay
    try:
        netstat = subprocess.run(
            ["cmd", "/c", f"netstat -ano | findstr :{CDP_PORT}"],
            capture_output=True, text=True, timeout=3
        )
        for line in netstat.stdout.splitlines():
            if "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(["taskkill", "/F", "/PID", pid, "/T"], capture_output=True)
                    closed = True
    except Exception:
        pass
        
    # 2. Đóng proc từ _LOGIN_CHROME_PROC nếu có
    if _LOGIN_CHROME_PROC is not None:
        try:
            _LOGIN_CHROME_PROC.terminate()
            _LOGIN_CHROME_PROC.wait(timeout=1.5)
            closed = True
        except Exception:
            try:
                _LOGIN_CHROME_PROC.kill()
                closed = True
            except Exception:
                pass
        _LOGIN_CHROME_PROC = None

    # 3. Thử qua Playwright CDP nếu vẫn còn sống
    if _cdp_alive():
        try:
            with sync_playwright() as p:
                b = p.chromium.connect_over_cdp(f"http://{CDP_HOST}:{CDP_PORT}", timeout=2000)
                b.close()
                closed = True
        except Exception:
            pass

    # 4. Fallback: Nếu profile vẫn còn bị khóa, dọn tiến trình chrome liên quan đến profile automation
    user_data = _chrome_user_data()
    if _is_profile_locked(user_data):
        try:
            ud_name = os.path.basename(user_data)
            cmd = f"Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Where-Object {{ $_.CommandLine -like '*{ud_name}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=5)
            closed = True
        except Exception as e:
            logger.warning("Không đóng được Chrome qua PowerShell: %s", e)

    time.sleep(0.5)
    return {"ok": True, "closed": closed, "is_running": _is_profile_locked(_chrome_user_data())}




def _chrome_user_data():
    """Thư mục User Data cho automation.
    KHÔNG được dùng thư mục Chrome mặc định: Chrome 151 chặn remote-debugging-port
    trên dir default (đã xác minh). Dùng profile riêng (đăng nhập 1 lần) nằm trong dự án.
    Nếu config AI_STUDIO_USER_DATA được set thì dùng dir đó (người dùng tự chịu)."""
    from ..core import config
    if getattr(config, 'AI_STUDIO_USER_DATA', None):
        return config.AI_STUDIO_USER_DATA
    return config.CHROME_PROFILE_DIR


def _chrome_profile():
    """Profile Chrome cho automation dir (mặc định profile duy nhất 'Default')."""
    from ..core import config
    return getattr(config, 'AI_STUDIO_PROFILE', 'Default')


def _chrome_exe():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("Không tìm thấy Google Chrome trên máy.")


def _cdp_alive():
    try:
        with urllib.request.urlopen(
                f"http://{CDP_HOST}:{CDP_PORT}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _bring_chrome_to_foreground(step):
    """Tìm cửa sổ Chrome và đưa lên foreground (ShowWindow + SetForegroundWindow).
    QUAN TRỌNG: FileChooser.set_files qua Playwright CDP chỉ hoạt động khi Chrome window
    hiển thị trên màn hình (không được minimize/ẩn). Đây là lý do tự bấm lỗi còn người
    dùng tự mở thì ít lỗi — khi user mở Chrome window → focus → set_files thành công."""
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32

        CHROME_CLASS = "Chrome_WidgetWin_1"
        found_hwnd = []

        def enum_cb(hwnd, lParam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == CHROME_CLASS:
                title_buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title_buf, 512)
                if user32.IsWindowVisible(hwnd):
                    found_hwnd.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        cb = WNDENUMPROC(enum_cb)
        user32.EnumWindows(cb, 0)

        if found_hwnd:
            hwnd = found_hwnd[0]
            SW_MAXIMIZE = 3  # Luôn phóng to toàn màn hình kích thước gốc, không thu nhỏ
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            user32.SetForegroundWindow(hwnd)
            step(f"Đã đưa Chrome lên toàn màn hình gốc (hwnd={hwnd}, maximized).")
        else:
            step("Không tìm thấy cửa sổ Chrome để đưa lên foreground (Chrome có thể đang khởi động).")
    except Exception as e:
        step(f"Bỏ qua đưa Chrome lên foreground ({e}).")


def _launch_automation_chrome(step):
    """B1 - Mở Google AI Studio trên Chrome profile riêng (ai_studio_auto) với cổng CDP.
    Dùng subprocess.Popen (CreateProcess giữ nguyên argv — không bị hỏng khoảng trắng);
    dir là NON-DEFAULT nên Chrome bind được cổng (đã xác minh).

    Cửa sổ luôn mở TOÀN MÀN HÌNH (start-maximized) để giữ kích thước gốc,
    đảm bảo thanh sidebar Model và Thinking Level hiển thị đầy đủ, không bị co nhỏ."""
    if _cdp_alive():
        step("Kết nối vào Chrome thật đang chạy (CDP).")
        _bring_chrome_to_foreground(step)
        return False

    # Nếu Chrome đang mở nhưng chưa có cổng CDP (do user vừa mở kiểm tra/đăng nhập),
    # tự động đóng và giải phóng profile để khởi động lại kèm cổng CDP, tránh bị kẹt timeout 25s
    if _is_profile_locked(_chrome_user_data()):
        step("Chrome đang mở ở chế độ đăng nhập. Đang tự động chuyển sang chế độ tự động hóa (CDP)...")
        close_automation_browser()
        time.sleep(0.8)

    step("Khởi động Chrome (profile automation) tại Google AI Studio...")
    os.makedirs(_chrome_user_data(), exist_ok=True)
    args = [
        _chrome_exe(),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={_chrome_user_data()}",
        f"--profile-directory={_chrome_profile()}",
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-restore-session-state",
        AI_STUDIO_URL,
    ]
    try:
        subprocess.Popen(args)
    except Exception as e:
        raise RuntimeError(f"Không khởi động được Chrome: {e}") from e
    deadline = time.time() + 25
    while time.time() < deadline:
        if _cdp_alive():
            step("Chrome đã sẵn sàng (CDP) tại Google AI Studio.")
            # Đưa Chrome lên foreground SAU KHI CDP ready (window đã tồn tại)
            time.sleep(1.5)  # Chờ window thực sự render xong
            _bring_chrome_to_foreground(step)
            return True
        time.sleep(0.5)
    raise RuntimeError(
        "Không nối được Chrome remote-debugging. "
        "Hãy đóng các cửa sổ Chrome đang mở rồi thử lại.")


def extract_script_from_text(text: str) -> str:
    """Trích xuất các dòng kịch bản dạng `MM:SS` hoặc `HH:MM:SS` + nội dung.
    Hỗ trợ ghép nối nhiều turn khi gõ 'tiếp' và tự động lọc trùng lặp các dòng lặp lại."""
    line_re = re.compile(r'^\s*(\d{1,3}:\d{2}(?::\d{2}(?:[.,]\d{1,3})?)?)\s+(.+)$')
    out = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = line_re.match(line)
        if m:
            entry = f"{m.group(1)}\t{m.group(2).strip()}"
            if entry not in seen:
                seen.add(entry)
                out.append(entry)
    return '\n'.join(out)


def _ensure_logged_in(page, step, _check):
    """Nếu bị redirect sang đăng nhập: CHỜ người dùng đăng nhập trong cửa sổ vừa mở
    (chỉ cần 1 lần — session sẽ còn lại cho các lần sau)."""
    if "accounts.google.com" in page.url:
        step("Profile automation chưa đăng nhập — hãy đăng nhập Google trong CỬA SỔ CHROME "
             "vừa mở (dùng account Gemini có quyền). Chờ tối đa 4 phút...")
        deadline = time.time() + 240
        while time.time() < deadline:
            _check()
            if "accounts.google.com" not in page.url and "aistudio.google.com" in page.url:
                step("Đã đăng nhập — tiếp tục.")
                return
            page.wait_for_timeout(2000)
        raise RuntimeError("Chưa đăng nhập được Google AI Studio trong 4 phút.")


def _model_normalize(name):
    """'Gemini 3.7 Flash' / 'gemini-3.7-flash' / 'Gemini 3.7 Flash Preview' → 'gemini 3 7 flash'."""
    import re
    return re.sub(r"[^a-z0-9]", " ", name.lower()).strip()


def _select_model(page, model, step):
    """B3 - Chọn model theo tên cấu hình (kèm verify/retry nếu click chưa ăn)."""
    if not model:
        step("Bỏ qua chọn model (không cấu hình).")
        return
    m = _model_normalize(model)
    if not m:
        step("Bỏ qua chọn model (cấu hình rỗng).")
        return

    def _current():
        try:
            return page.locator("ms-model-selector button span.title").first.inner_text(timeout=5000).strip()
        except Exception:
            return "?"

    try:
        for attempt in range(2):
            cur = _current()
            if _model_normalize(cur) == m:
                step(f"Model đã đúng: {cur}")
                return
            step(f"Chọn model: muốn '{model}', đang dùng '{cur}' (lần {attempt + 1}).")
            btn = page.locator("ms-model-selector button").first
            btn.wait_for(state="visible", timeout=12000)
            btn.click(force=True)
            # đợi panel render danh sách model (không đọc vội → nghĩ trống)
            names_el = page.locator(".model-title-text")
            names = []
            try:
                names_el.first.wait_for(state="visible", timeout=6000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            for i in range(names_el.count()):
                try:
                    names.append(names_el.nth(i).inner_text(timeout=3000).strip() or "")
                except Exception:
                    names.append("")
            step(f"Model có sẵn ({len(names)}): {names}")
            try:
                all_btn = page.locator('button[data-test-category-button]:has-text("All")').first
                if all_btn.is_visible(timeout=1000):
                    all_btn.click(force=True)
                    page.wait_for_timeout(600)
            except Exception:
                pass
            target = None
            for idx, name in enumerate(names):
                if name and _model_normalize(name) == m:
                    target = names_el.nth(idx)
                    break
            if target is None:
                for idx, name in enumerate(names):
                    if name and m and m in _model_normalize(name):
                        target = names_el.nth(idx)
                        break
            if target:
                target.scroll_into_view_if_needed(timeout=5000)
                target.click(force=True)
                try:
                    page.locator("mat-mdc-menu-panel").first.wait_for(state="hidden", timeout=5000)
                except Exception:
                    page.keyboard.press("Escape")
                page.wait_for_timeout(700)
                if _model_normalize(_current()) == m:
                    step(f"Đã chọn model: {cur and model}")
                    return
                step("Click model chưa hiệu lực → thử lại.")
            else:
                page.keyboard.press("Escape")
                step(f"Không có model {model} trong danh sách → giữ mặc định.")
                return
        step("Không chọn được model theo cấu hình → giữ model hiện tại.")
    except Exception as e:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        step(f"Chọn model lỗi (giữ mặc định): {e}")


def _set_thinking_level(page, step):
    """B4 - Chế độ: Bật Thinking Level = High."""
    try:
        page.wait_for_timeout(1200)  # Đợi sidebar ổn định sau khi đổi model
        sel = page.locator('mat-select[aria-label*="Thinking"], mat-select[aria-label="Thinking Level"]').first
        if sel.is_visible(timeout=3000):
            sel.click(timeout=3000)
            page.wait_for_timeout(500)
            opt = page.locator(".mat-mdc-option, mat-option").filter(has_text="High").first
            if opt.is_visible(timeout=3000):
                opt.click(force=True)
                step("Chế độ: Thinking Level = High.")
                page.wait_for_timeout(500)
                return
            else:
                page.keyboard.press("Escape")
        step("Chế độ: Mặc định (model không có tùy chọn Thinking Level).")
    except Exception as e:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        step(f"Chế độ Thinking: giữ mặc định ({e}).")


def _upload_cache_path(video_path):
    """Path bản nhỏ cache cho upload. Khóa theo base name + size + mtime của source
    (source đổi → path khác → tự nén lại); file đã nén xong được GIỮ LẠI, không xoá."""
    import hashlib
    st = os.stat(video_path)
    key = f"{os.path.basename(video_path)}|{st.st_size}|{int(st.st_mtime)}"
    h = hashlib.md5(key.encode('utf-8', errors='ignore')).hexdigest()[:10]
    from ..core import config
    return os.path.join(config.MANUAL_DIR, f"_studio_upload_{h}.mp4")


def _get_or_make_upload_copy(video_path, max_mb, step):
    """Nén bản ≤ max_mb một lần rồi cache: lần sau tái dùng nếu file hợp lệ.
    Nén sang .tmp rồi rename atomic — tránh giữ file lừa nếu bị ngắt giữa chừng."""
    from .video_service import make_studio_upload_copy
    cache_path = _upload_cache_path(video_path)
    if os.path.exists(cache_path):
        sz = os.path.getsize(cache_path)
        if 0 < sz <= max_mb * 1024 * 1024:
            step(f"Dùng bản nhỏ đã nén sẵn ({sz/1e6:.0f}MB) — không nén lại.")
            return cache_path
    step(f"Tạo bản nhỏ ≤{max_mb:.0f}MB để đính kèm (cache, lần sau tái dùng)...")
    # Tên tạm PHẢI kết thúc .mp4 (ffmpeg nhận diện format từ extension) — rename atomic sau
    # khi nén xong (tránh giữ file lừa nếu bị ngắt giữa chừng).
    tmp_path = os.path.splitext(cache_path)[0] + ".tmp.mp4"
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        pass
    make_studio_upload_copy(video_path, max_mb, tmp_path)
    os.replace(tmp_path, cache_path)
    return cache_path


def _upload_file(page, video_path, step, _check):
    """B5 - Upload video qua File Chooser (không dùng hộp thoại Windows).

    Playwright CDP KHÔNG set_files được file lớn trên browser ngoài (chặn >50MB,
    treo cỡ ~46MB) — chỉ tin cậy vùng ≤ AI_STUDIO_UPLOAD_MAX_MB. Nếu file gốc lớn
    hơn ngưỡng thì nén thêm 1 bản ≤ ngưỡng (video_service.make_studio_upload_copy),
    giữ cache để các lần sau không nén lại."""
    from ..core import config

    max_mb = float(getattr(config, 'AI_STUDIO_UPLOAD_MAX_MB', 25) or 25)
    to_upload = video_path
    size = 0
    try:
        size = os.path.getsize(video_path)
    except Exception:
        pass
    if size > max_mb * 1024 * 1024:
        to_upload = _get_or_make_upload_copy(video_path, max_mb, step)

    # Bắt buộc đưa Chrome lên foreground TRƯỚC KHI upload:
    # FileChooser.set_files qua Playwright CDP timeout khi Chrome window ẩn/minimize.
    _bring_chrome_to_foreground(step)
    page.wait_for_timeout(800)

    try:
        step("Bấm nút đính kèm (➕)...")
        add = page.locator('button[data-test-id="add-media-button"]')
        add.wait_for(state="visible", timeout=20000)
        add.click()
        page.wait_for_timeout(900)
        _check()
        with page.expect_file_chooser(timeout=15000) as fc_info:
            up = page.locator("button.upload-file-menu-item").first
            up.wait_for(state="visible", timeout=6000)
            up.click()
        # Thử set_files; nếu timeout thì đưa Chrome foreground lần nữa rồi retry 1 lần
        try:
            fc_info.value.set_files(os.path.abspath(to_upload))
        except Exception as set_err:
            step(f"set_files lần 1 thất bại ({set_err}) → đưa Chrome foreground, retry...")
            _bring_chrome_to_foreground(step)
            page.wait_for_timeout(1500)
            # Mở lại file chooser lần 2
            add.click()
            page.wait_for_timeout(900)
            _check()
            with page.expect_file_chooser(timeout=20000) as fc_info2:
                up2 = page.locator("button.upload-file-menu-item").first
                up2.wait_for(state="visible", timeout=6000)
                up2.click()
            fc_info2.value.set_files(os.path.abspath(to_upload))
        step("Đã đính kèm video.")
    except Exception as e:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        raise RuntimeError(f"Không upload được video (menu đính kèm đổi): {e}")


def _run_button(page):
    """Tìm nút Run trên Google AI Studio qua các selector phổ biến.
    Lọc bỏ các nút đính kèm (+), tune model để tránh click nhầm."""
    selectors = [
        "ms-run-button button",
        "button.run-button",
        'button[aria-label*="Run cell"]',
        'button[aria-label*="Run"]',
        'button[data-test-id*="run-button"]',
        'button:has-text("Run")',
        'button[aria-label*="Send"]',
        'button:has-text("Send")',
        "button.send-button",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = loc.count()
            for i in range(count):
                el = loc.nth(i)
                if el.is_visible():
                    tid = (el.get_attribute("data-test-id") or "").lower()
                    aria = (el.get_attribute("aria-label") or "").lower()
                    if "add" in tid or "media" in tid or "tune" in aria or "model" in aria:
                        continue
                    return el
        except Exception:
            continue
    return page.locator("ms-run-button button").first


def _is_run_button_ready(btn):
    """True nếu nút Run đã sáng, sẵn sàng click (không disabled/loading)."""
    try:
        if not btn or btn.count() == 0:
            return False
        el = btn.first
        if not el.is_visible():
            return False
        aria_dis = el.get_attribute("aria-disabled")
        if aria_dis and aria_dis.strip().lower() == "true":
            return False
        dis = el.get_attribute("disabled")
        if dis is not None:
            return False
        classes = (el.get_attribute("class") or "").lower()
        if "disabled" in classes or "mat-button-disabled" in classes:
            return False
        return el.is_enabled()
    except Exception:
        return False


def _prompt_editor(page):
    """Tìm ô soạn thảo prompt (hỗ trợ cả contenteditable div và textarea)."""
    selectors = [
        'ms-prompt-editor [contenteditable="true"]',
        'ms-prompt-editor textarea',
        'div[contenteditable="true"]',
        'textarea[placeholder*="prompt"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    try:
        by_ph = page.get_by_placeholder("Start typing a prompt")
        if by_ph.count() > 0 and by_ph.first.is_visible():
            return by_ph.first
    except Exception:
        pass
    return page.locator('ms-prompt-editor [contenteditable="true"], ms-prompt-editor textarea').first


def _is_stop_button_visible(page):
    """True nếu nút Stop đang hiển thị (tức Gemini đang trong quá trình sinh kịch bản)."""
    try:
        stops = page.locator('button:has-text("Stop"), ms-run-button button:has-text("Stop"), button[aria-label*="Stop"]')
        for i in range(stops.count()):
            if stops.nth(i).is_visible():
                return True
    except Exception:
        pass
    try:
        btn = _run_button(page)
        if btn and btn.is_visible():
            txt = (btn.inner_text() or "").strip().lower()
            aria = (btn.get_attribute("aria-label") or "").strip().lower()
            if "stop" in txt or "stop" in aria:
                return True
            if btn.locator('mat-icon:has-text("stop"), [data-mat-icon-name="stop"]').count() > 0:
                return True
    except Exception:
        pass
    return False


def _get_model_turn_text(page):
    """Đọc text từ model turn cuối cùng (TUYỆT ĐỐI không lấy user turn / prompt)."""
    try:
        turns = page.locator("ms-chat-turn")
        count = turns.count()
        if not count:
            return ""
        for i in range(count - 1, -1, -1):
            t = turns.nth(i)
            cls = (t.get_attribute("class") or "").lower()
            if "user" in cls or t.locator(".chat-turn-container.user, .user-turn").count() > 0:
                continue
            if "model" in cls or t.locator(".chat-turn-container.model, .model-turn").count() > 0:
                chunks = t.locator("ms-text-chunk")
                if chunks.count():
                    parts = [chunks.nth(j).inner_text().strip() for j in range(chunks.count()) if chunks.nth(j).inner_text().strip()]
                    combined = "\n".join(parts).strip()
                    if combined and "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in combined and "Bạn là biên kịch anime" not in combined:
                        return combined
                txt = (t.inner_text() or "").strip()
                if txt and "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in txt and "Bạn là biên kịch anime" not in txt:
                    return txt
    except Exception:
        pass
    return ""


def _get_all_model_turns_text(page):
    """Đọc và ghép nội dung từ TẤT CẢ các turn của model (TUYỆT ĐỐI không đọc prompt của User)."""
    try:
        turns = page.locator("ms-chat-turn")
        count = turns.count()
        if not count:
            return ""
        all_model_texts = []
        for i in range(count):
            t = turns.nth(i)
            cls = (t.get_attribute("class") or "").lower()
            # Bỏ qua user turn
            if "user" in cls or t.locator(".chat-turn-container.user, .user-turn").count() > 0:
                continue

            # Chỉ nhận model turn
            if "model" in cls or t.locator(".chat-turn-container.model, .model-turn").count() > 0:
                chunks = t.locator("ms-text-chunk")
                parts = []
                for c_idx in range(chunks.count()):
                    txt = (chunks.nth(c_idx).inner_text() or "").strip()
                    if txt:
                        parts.append(txt)
                if parts:
                    combined = "\n".join(parts).strip()
                    # Loại trừ nếu bị lẫn prompt của user
                    if "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in combined and "Bạn là biên kịch anime" not in combined:
                        all_model_texts.append(combined)
                else:
                    # Fallback lấy text thuần nếu chưa có chunk
                    txt = (t.inner_text() or "").strip()
                    if txt and "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in txt and "Bạn là biên kịch anime" not in txt:
                        all_model_texts.append(txt)
        if all_model_texts:
            return "\n\n".join(all_model_texts).strip()
    except Exception:
        pass
    return ""


# Từ khóa lỗi NGHIÊM TRỌNG (chỉ những lỗi không thể tự phục hồi sau khi click lại)
_FATAL_ERROR_KEYWORDS = [
    "account suspended",
    "account has been disabled",
    "billing account disabled",
]
# Từ khóa lỗi TẠM THỜI (Google cho phép thử lại: 'Please try again', nghẽn mạng, đồng bộ video...)
_TRANSIENT_ERROR_KEYWORDS = [
    "permission denied",
    "failed to generate content",
    "an internal error has occurred",
    "internal error",
    "rate limit",
    "server error",
    "model overloaded",
    "overloaded",
    "try again",
    "please wait",
    "quota",
    "an error occurred",
    "something went wrong",
    "error generating response",
    "response was filtered",
    "unable to generate",
    "generation stopped",
]


def _detect_studio_error(page):
    """Kiểm tra lỗi từ AI Studio.
    Trả về tuple (is_fatal, error_text) hoặc None nếu không có lỗi.
    - is_fatal=True: lỗi nghiêm trọng (account suspended...) → không retry, ném RuntimeError.
    - is_fatal=False: lỗi tạm thời (overloaded, internal error...) → có thể retry.
    ĐẶC BIỆT: Không bao giờ báo lỗi khi nút Stop đang hiển thị (Gemini đang sinh kịch bản).

    CHỈ kiểm tra snackbar/banner/alert của UI — KHÔNG kiểm tra nội dung kịch bản AI viết
    vì kịch bản có thể chứa từ như 'error', 'try again', 'generation stopped'... gây false positive.
    """
    if _is_stop_button_visible(page):
        return None

    # 1. Kiểm tra snackbar/banner/alert (UI error của AI Studio — rõ ràng nhất)
    try:
        alerts = page.locator('mat-snack-bar-container, .error-banner, ms-banner, [role="alert"], .error-container, .error-message')
        for i in range(alerts.count()):
            el = alerts.nth(i)
            if el.is_visible():
                txt = (el.inner_text() or "").strip()
                if txt and len(txt) > 8:
                    txt_lower = txt.lower()
                    for kw in _FATAL_ERROR_KEYWORDS:
                        if kw in txt_lower:
                            return (True, txt)
                    for kw in _TRANSIENT_ERROR_KEYWORDS:
                        if kw in txt_lower:
                            return (False, txt)
    except Exception:
        pass

    # 2. Kiểm tra chat turn có thông báo lỗi đặc thù của Google (như 'permission denied', 'failed to generate content')
    try:
        err_turns = page.locator('ms-chat-turn:has-text("permission denied"), ms-chat-turn:has-text("Failed to generate content"), ms-chat-turn:has-text("internal error")')
        if err_turns.count() > 0 and err_turns.last.is_visible():
            txt = (err_turns.last.inner_text() or "").strip()
            if txt and len(txt) > 10:
                txt_lower = txt.lower()
                for kw in _FATAL_ERROR_KEYWORDS:
                    if kw in txt_lower:
                        return (True, txt)
                for kw in _TRANSIENT_ERROR_KEYWORDS:
                    if kw in txt_lower:
                        return (False, txt)
    except Exception:
        pass

    return None


def _click_run_with_mouse(page, btn):
    """Mô phỏng click chuột thật (native mouse event qua CDP) vào tâm nút Run."""
    try:
        box = btn.bounding_box()
        if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
            cx = box['x'] + box['width'] / 2
            cy = box['y'] + box['height'] / 2
            # Di chuyển chuột mượt mô phỏng người dùng thật
            page.mouse.move(cx, cy, steps=6)
            page.wait_for_timeout(150)
            page.mouse.down()
            page.wait_for_timeout(80)
            page.mouse.up()
            return True
    except Exception:
        pass
    # Fallback click phần tử
    try:
        btn.click(force=True)
        return True
    except Exception:
        return False


def _wait_processing(page, step, _check, max_sec=90):
    """B7 - Chờ AI Studio xử lý/index video xong.
    Phản ứng tức thì: chỉ chờ khi thanh progress bar hoặc spinner đang thực sự chạy.
    Ngay khi nút Run khả dụng (enabled), video đã hoàn tất, không chờ lãng phí!
    """
    step("Chờ AI Studio xử lý/index video...")
    deadline = time.time() + max_sec

    while time.time() < deadline:
        _check()

        # Kiểm tra xem có thanh tiến trình hoặc spinner nào đang bận không
        is_busy = False
        try:
            bars = page.locator("mat-progress-bar, mat-progress-spinner, mat-spinner, .file-loading, [role='progressbar']")
            for i in range(bars.count()):
                if bars.nth(i).is_visible():
                    is_busy = True
                    break
        except Exception:
            pass

        # Nếu không có thanh tiến trình nào đang chạy, kiểm tra nút Run
        if not is_busy:
            btn = _run_button(page)
            if _is_run_button_ready(btn):
                step("Video đã index xong, nút Run đã sẵn sàng.")
                break

        # Nếu model đã có chữ thì cũng thoát luôn
        try:
            mt = page.locator('.chat-turn-container.model, ms-chat-turn.model')
            if mt.count() and _get_model_turn_text(page):
                step("Model đã bắt đầu sinh nội dung.")
                return
        except Exception:
            pass

        page.wait_for_timeout(1000)

    # Đệm an toàn 15s: Google Cloud Storage cần thời gian để phân quyền IAM token cho file video
    # với Gemini Inference. Bấm quá sớm (<10s) sẽ sinh lỗi 'Failed to generate content: permission denied'.
    step("Đệm an toàn 15s để Google Cloud phân quyền video (tránh lỗi permission denied)...")
    for sec_left in range(15, 0, -3):
        _check()
        step(f"Đang chờ Google Cloud hoàn tất phân quyền video... còn {sec_left}s")
        page.wait_for_timeout(3000)
    step("Video đã hoàn toàn sẵn sàng và phân quyền xong để gửi prompt.")


def _fill_prompt(page, prompt, step, _check):
    """B7 - Điền prompt vào ô nhập NHANH.
    Dùng PASTE (Ctrl+V) — insert_text gõ từng ký tự nên lâu với prompt dài."""
    box = _prompt_editor(page)
    box.wait_for(state="visible", timeout=20000)
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    filled = False
    try:
        page.evaluate("(t) => navigator.clipboard.writeText(t)", prompt)
        page.wait_for_timeout(200)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(600)
        shown = ""
        try:
            shown = (box.input_value() or box.inner_text() or "").strip()
        except Exception:
            shown = ""
        if shown:
            filled = True
    except Exception:
        filled = False
    if not filled:
        # Fallback: gõ từng ký tự
        page.keyboard.insert_text(prompt)
        page.wait_for_timeout(500)
    shown = ""
    try:
        shown = (box.input_value() or box.inner_text() or "").strip()
    except Exception:
        shown = ""
    if not shown:
        try:
            shown = (page.evaluate("() => document.querySelector('ms-prompt-editor')?.innerText || ''") or "").strip()
        except Exception:
            shown = ""
    if not shown:
        raise RuntimeError("Không điền được prompt vào composer (giá trị rỗng).")
    step(f"Đã điền prompt ({len(shown)} ký tự)"
         f"{' (paste)' if filled else ' (gõ từng ký tự)'}.")


def _is_generating(page, initial_turns_count=0):
    """Xác minh prompt ĐÃ ĐƯỢC GỬI THỰC SỰ:
    1. Nút Stop xuất hiện (đang generate).
    2. Số lượng chat turn tăng lên (> initial_turns_count).
    3. Model turn có chữ mới đang sinh ra (> 20 ký tự).
    4. Ô composer đã bị làm rỗng (text prompt đã được đẩy đi).
    """
    # 1. Có nút Stop đang hiển thị
    try:
        stop_btn = page.locator('button:has-text("Stop"), ms-run-button button:has-text("Stop"), button[aria-label*="Stop"]')
        if stop_btn.count() > 0 and stop_btn.first.is_visible():
            return True
    except Exception:
        pass

    # 2. Số lượng chat turn tăng lên
    try:
        cur_turns = page.locator("ms-chat-turn").count()
        if cur_turns > initial_turns_count:
            return True
    except Exception:
        pass

    # 3. Model turn có text mới
    try:
        txt = _get_model_turn_text(page)
        if txt and len(txt) > 20:
            return True
    except Exception:
        pass

    # 4. Ô soạn thảo đã rỗng (text đã được gửi đi)
    try:
        editor = _prompt_editor(page)
        val = (editor.input_value() if hasattr(editor, 'input_value') else "") or (editor.inner_text() or "").strip()
        if not val or len(val) == 0:
            return True
    except Exception:
        pass

    return False


def _wait_until_run_ready(page, step, _check, timeout_sec=60):
    """Đợi nút Run thực sự sẵn sàng và enabled trước khi click.
    Đây là bước then chốt để tránh click quá sớm như trong trường hợp user thủ công thành công
    nhưng auto click bị lỗi khi page chưa ổn định hoặc button đang disabled/overlay.
    """
    deadline = time.time() + timeout_sec
    last_msg_t = 0
    while time.time() < deadline:
        _check()
        btn = _run_button(page)
        if _is_run_button_ready(btn):
            return btn
        now = time.time()
        if now - last_msg_t >= 5:
            last_msg_t = now
            # Log chi tiết trạng thái nút để debug
            try:
                el = btn.first
                vis = el.is_visible()
                aria_dis = el.get_attribute("aria-disabled") or ""
                dis = el.get_attribute("disabled")
                cls = (el.get_attribute("class") or "")[:80]
                enabled = el.is_enabled()
                step(f"Đợi nút Run sẵn sàng... vis={vis}, aria-disabled='{aria_dis}', disabled={dis is not None}, enabled={enabled}, class={cls!r}")
            except Exception as dbg_e:
                step(f"Đợi nút Run sẵn sàng... (lỗi debug: {dbg_e})")
        page.wait_for_timeout(500)
    btn = _run_button(page)
    if _is_run_button_ready(btn):
        return btn
    raise RuntimeError("Nút Run không ở trạng thái sẵn sàng sau khi chờ đủ thời gian.")


def _get_dpi_scale():
    """Lấy DPI scale factor của màn hình chính (Windows). Trả về 1.0 nếu không lấy được."""
    try:
        import ctypes
        # Đảm bảo process aware DPI để GetSystemMetrics trả về physical pixel
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        user32 = ctypes.windll.user32
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        if dpi and dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _get_element_screen_pos(page, vx, vy, step=None):
    """Tính toán tọa độ màn hình thực tế (Physical Screen Coordinates) chuẩn xác 100%.
    Dùng Win32 ClientToScreen trên RenderWidgetHostHWND (DPI-Aware) để lấy gốc tọa độ,
    rồi cộng với (vx, vy) * devicePixelRatio.
    """
    try:
        import ctypes
        from ctypes import wintypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        user32 = ctypes.windll.user32
        dpr = page.evaluate("window.devicePixelRatio || 1")

        found = []
        def enum_w(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "Chrome_WidgetWin_1" and user32.IsWindowVisible(hwnd):
                def child_cb(c_hwnd, _):
                    c_buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(c_hwnd, c_buf, 256)
                    if c_buf.value == "Chrome_RenderWidgetHostHWND":
                        rect = wintypes.RECT()
                        user32.GetClientRect(c_hwnd, ctypes.byref(rect))
                        if rect.right > 300 and rect.bottom > 200:
                            pt = wintypes.POINT(0, 0)
                            user32.ClientToScreen(c_hwnd, ctypes.byref(pt))
                            found.append((pt.x, pt.y))
                    return True
                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                user32.EnumChildWindows(hwnd, WNDENUMPROC(child_cb), 0)
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_w), 0)

        if found:
            origin_x, origin_y = found[0]
            phys_x = int(origin_x + vx * dpr)
            phys_y = int(origin_y + vy * dpr)
            if step:
                step(f"[Tọa độ chuột chuẩn] Viewport ({int(vx)}, {int(vy)}) × {dpr:.2f} + Gốc Chrome ({origin_x}, {origin_y}) → Màn hình ({phys_x}, {phys_y})")
            return phys_x, phys_y
    except Exception as e:
        if step:
            step(f"[Tọa độ Win32 lỗi: {e}] → dùng fallback JS")

    # Fallback qua JS nếu không enum được HWND
    try:
        geom = page.evaluate("""() => {
            const dpr = window.devicePixelRatio || 1;
            return {
                screenX: window.screenX || window.screenLeft || 0,
                screenY: window.screenY || window.screenTop || 0,
                outerW: window.outerWidth || 0,
                outerH: window.outerHeight || 0,
                innerW: window.innerWidth || 0,
                innerH: window.innerHeight || 0,
                dpr: dpr,
            };
        }""")
        dpr = geom.get('dpr', 1.0)
        sx = geom.get('screenX', 0)
        sy = geom.get('screenY', 0)
        ow = geom.get('outerW', 0)
        iw = geom.get('innerW', 0)
        oh = geom.get('outerH', 0)
        ih = geom.get('innerH', 0)
        border_w = max(0, (ow - iw) // 2)
        header_h = max(0, oh - ih - border_w)
        origin_lx = sx + border_w
        origin_ly = sy + header_h
        elem_lx = origin_lx + vx
        elem_ly = origin_ly + vy
        phys_x = int(elem_lx * dpr)
        phys_y = int(elem_ly * dpr)
        return phys_x, phys_y
    except Exception:
        pass

    return None


def _move_physical_mouse(target_x, target_y, duration=0.4):
    """Di chuyển con trỏ chuột vật lý theo đường cong Bézier tự nhiên như tay người thật (Human-like curve).
    Mô phỏng gia tốc sinh học (chậm lúc bắt đầu, lướt ở giữa, giảm tốc khi tới đích) và độ rung vi mô (micro-jitter).
    Vượt qua kiểm tra hành vi chuột (Mouse Biometrics) của Google reCAPTCHA / Antibot.
    """
    try:
        import random
        import math
        import ctypes
        user32 = ctypes.windll.user32
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        start_x, start_y = pt.x, pt.y

        dx = target_x - start_x
        dy = target_y - start_y
        dist = math.hypot(dx, dy)
        if dist < 5:
            user32.SetCursorPos(int(target_x), int(target_y))
            return

        # Điểm uốn Bézier ngẫu nhiên (mô phỏng độ cong tự nhiên của cổ tay)
        ctrl_x = start_x + dx * random.uniform(0.35, 0.65) + random.uniform(-25, 25)
        ctrl_y = start_y + dy * random.uniform(0.35, 0.65) + random.uniform(-20, 20)

        steps = max(18, int(dist / 10))
        interval = max(0.008, duration / steps)
        for i in range(1, steps + 1):
            t = i / steps
            # Cosine ease-in-out: tăng tốc rồi hãm phanh tự nhiên
            t_ease = (1 - math.cos(t * math.pi)) / 2
            bx = (1 - t_ease)**2 * start_x + 2 * (1 - t_ease) * t_ease * ctrl_x + t_ease**2 * target_x
            by = (1 - t_ease)**2 * start_y + 2 * (1 - t_ease) * t_ease * ctrl_y + t_ease**2 * target_y
            # Micro-jitter nhỏ của cơ tay người
            jx = random.uniform(-1, 1) if i < steps else 0
            jy = random.uniform(-1, 1) if i < steps else 0
            user32.SetCursorPos(int(bx + jx), int(by + jy))
            time.sleep(interval)

        user32.SetCursorPos(int(target_x), int(target_y))
        return
    except Exception:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.moveTo(target_x, target_y, duration=duration)
        except Exception:
            pass


def _user_like_click(page, btn, step):
    """Mô phỏng 100% thao tác người dùng:
    1. Di chuyển con trỏ chuột Windows đến đúng vị trí nút (tọa độ vật lý, có DPI scale).
    2. Dừng lại ~400ms (hover) rồi mới ấn.
    3. Nhấn đúng 1 lần chuột thật bằng pyautogui/Win32 (click vật lý OS, không phải synthetic).
    TUYỆT ĐỐI không dùng Ctrl+Enter."""
    try:
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
    except Exception:
        pass

    box = None
    try:
        box = btn.bounding_box()
    except Exception:
        box = None

    step(f"Bounding box nút: {box}")
    if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
        cx = box['x'] + box['width'] / 2
        cy = box['y'] + box['height'] / 2

        # 1. Tính tọa độ vật lý màn hình (physical pixel, DPI-aware)
        screen_pos = _get_element_screen_pos(page, cx, cy, step=step)

        # 2. Di chuyển con trỏ chuột vật lý đến đúng vị trí
        if screen_pos:
            sx, sy = screen_pos
            step(f"Di chuyển chuột đến nút: màn hình ({int(sx)}, {int(sy)}), viewport ({int(cx)}, {int(cy)})...")
            _move_physical_mouse(sx, sy, duration=0.3)
        else:
            step(f"Không tính được tọa độ vật lý, viewport ({int(cx)}, {int(cy)})...")

        # 3. Playwright CDP cũng move để hover kích hoạt highlight nút
        try:
            page.mouse.move(cx, cy, steps=8)
        except Exception:
            pass
        try:
            btn.hover(timeout=2000)
        except Exception:
            pass

        # 4. Dừng lại tại vị trí nút ~400ms rồi mới ấn
        step("Chuột đã ở đúng vị trí, dừng 400ms rồi ấn click vật lý...")
        page.wait_for_timeout(400)

        # 5. KÍCH HOẠT SỰ KIỆN CLICK CHUẨN XÁC VÀO TRÌNH DUYỆT CHROME
        #    Thực nghiệm chứng minh: Chrome Sandbox chặn mouse_event từ tiến trình ngoài.
        #    Chỉ có Playwright CDP (Input.dispatchMouseEvent) mới kích hoạt được sự kiện click
        #    trong Chrome với đầy đủ cờ isTrusted = true, userActive = true (User Activation thật).
        clicked = False

        # 5. KÍCH HOẠT DUY NHẤT 1 LẦN CLICK VÀO NÚT RUN (TUYỆT ĐỐI KHÔNG CLICK LẦN 2)
        #    Nếu click 2 lần liên tiếp: click 1 bật Run → biến thành nút Stop,
        #    click 2 đập thẳng vào nút Stop vừa hiện → HỦY NGAY LẬP TỨC!
        clicked = False
        try:
            page.mouse.click(cx, cy)
            clicked = True
            step(f"Đã ấn 1 lần chuột duy nhất vào nút Run tại ({int(cx)}, {int(cy)}).")
        except Exception as e:
            step(f"page.mouse.click gặp lỗi ({e}), chuyển sang btn.click...")
            try:
                btn.click(force=True, timeout=3000)
                clicked = True
                step("Đã kích hoạt click qua btn.click(force=True).")
            except Exception as e2:
                step(f"btn.click lỗi: {e2}")

        # Sau khi ấn: di chuyển nhẹ con trỏ chuột ra khỏi nút (tránh hover làm đè lên nút Stop)
        try:
            page.mouse.move(cx - 100, cy, steps=4)
        except Exception:
            pass

        page.wait_for_timeout(500)
        return clicked

    # Fallback nếu không có bounding box
    try:
        btn.hover(timeout=2000)
        page.wait_for_timeout(400)
        btn.click(force=True, timeout=4000)
        return True
    except Exception:
        pass

    try:
        page.evaluate("(el) => { if (el) { el.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})); el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); } }", btn)
        return True
    except Exception:
        return False


def _type_and_click_send(page, text="tiếp", step=None):
    """Mô phỏng 100% người dùng bình thường:
    1. Đưa Chrome lên foreground, focus tab.
    2. Di chuyển con trỏ chuột vào ô soạn thảo prompt, dừng lại một nhịp rồi mới click.
    3. Xóa sạch nội dung cũ (Ctrl+A, Backspace).
    4. Gõ từng ký tự của chữ 'tiếp' với độ trễ phím tự nhiên.
    5. Đợi ~1s để hệ thống phản hồi và nút gửi sáng lên.
    6. Chờ nút Run/Send sẵn sàng.
    7. Di chuyển con trỏ chuột đến đúng vị trí nút gửi, dừng lại rồi mới ấn bằng chuột.
    TUYỆT ĐỐI KHÔNG DÙNG Ctrl+Enter vì gây lỗi trên AI Studio."""
    def _log(msg):
        if step:
            try:
                step(msg)
            except Exception:
                pass
        else:
            logger.info("AIStudio: %s", msg)

    _log(f"Mô phỏng người dùng: gõ '{text}' và click gửi bằng chuột...")
    _bring_chrome_to_foreground(_log)
    try:
        page.bring_to_front()
        page.evaluate("window.focus()")
    except Exception:
        pass

    page.wait_for_timeout(1000)

    # 1. Tìm ô soạn thảo prompt và di chuyển chuột vào vị trí, dừng lại rồi mới click
    editor = _prompt_editor(page)
    try:
        editor.wait_for(state="visible", timeout=10000)
        box = editor.bounding_box()
        if box and box.get('width', 0) > 0 and box.get('height', 0) > 0:
            cx = box['x'] + min(40, box['width'] / 4)
            cy = box['y'] + box['height'] / 2
            screen_pos = _get_element_screen_pos(page, cx, cy)
            if screen_pos:
                _move_physical_mouse(screen_pos[0], screen_pos[1], duration=0.25)
            page.mouse.move(cx, cy, steps=6)
            try:
                editor.hover(timeout=2000)
            except Exception:
                pass
            page.wait_for_timeout(300)  # Để con trỏ chuột vào vị trí rồi mới ấn
            page.mouse.click(cx, cy)
        else:
            editor.click()
    except Exception as e:
        _log(f"Click vào ô prompt fallback: {e}")
        try:
            editor.click()
        except Exception:
            pass

    page.wait_for_timeout(300)

    # 2. Xóa sạch nội dung cũ trong ô prompt
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(200)

    # 3. Gõ từng ký tự như người dùng thật
    typed = False
    try:
        page.keyboard.type(text, delay=80)
        page.wait_for_timeout(300)
        val = ""
        try:
            val = (editor.input_value() if hasattr(editor, 'input_value') else "") or (editor.inner_text() or "").strip()
        except Exception:
            pass
        if text in val:
            typed = True
    except Exception:
        pass

    if not typed:
        try:
            page.evaluate("(t) => navigator.clipboard.writeText(t)", text)
            page.wait_for_timeout(150)
            page.keyboard.press("Control+V")
            page.wait_for_timeout(300)
        except Exception:
            pass

    _log(f"Đã gõ chữ '{text}', đợi 1s trước khi click nút gửi...")
    page.wait_for_timeout(1000)

    # 4. Tìm nút Run/Send và chờ sáng
    btn = _run_button(page)
    for _ in range(12):
        if _is_run_button_ready(btn):
            break
        page.wait_for_timeout(500)
        btn = _run_button(page)

    # 5. Di chuyển con trỏ chuột đến đúng vị trí nút gửi, dừng lại rồi mới ấn bằng chuột
    try:
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
    except Exception:
        pass

    clicked = _user_like_click(page, btn, _log)
    if not clicked:
        try:
            btn.click(force=True)
            clicked = True
        except Exception:
            pass

    if clicked:
        _log("Đã click nút gửi bằng chuột thành công (không dùng Ctrl+Enter).")
    else:
        _log("Cảnh báo: Chưa click được nút gửi bằng chuột.")

    page.wait_for_timeout(2000)


def _send_continue_command(page, text="tiếp", step=None):
    """Gửi lệnh text tiếp tục gen sau lỗi: gõ chữ 'tiếp' và click gửi bằng chuột (không dùng Ctrl+Enter)."""
    _type_and_click_send(page, text=text, step=step)


def _auto_submit(page, step, _check, max_attempts=4):
    """B8 - Tự gửi prompt bằng cách CLICK TRỰC TIẾP NÚT RUN BẰNG CHUỘT:
    Mô phỏng 100% thao tác tay của người dùng (di chuyển chuột vào nút Run và click 1 lần duy nhất).
    TUYỆT ĐỐI không dùng Control+Enter vì trên AI Studio phím tắt này gây lỗi.
    Sau khi click, kiên nhẫn chờ Gemini phản hồi (tối đa 25s), không click liên tiếp dồn dập.
    Nếu Google báo 'An internal error has occurred' do video chưa kịp đồng bộ, chờ 5s rồi bấm lại nút Run.
    """
    initial_turns = 0
    try:
        initial_turns = page.locator("ms-chat-turn").count()
    except Exception:
        initial_turns = 0

    for attempt in range(1, max_attempts + 1):
        _check()
        step(f"Tự động nhấn nút Run bằng chuột (lần {attempt}/{max_attempts})...")

        _bring_chrome_to_foreground(step)
        try:
            page.bring_to_front()
            page.evaluate("window.focus()")
        except Exception:
            pass

        btn = _wait_until_run_ready(page, step, _check, timeout_sec=30)
        try:
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
        except Exception:
            pass

        clicked = _user_like_click(page, btn, step)
        if not clicked:
            raise RuntimeError("Không thể click được nút Run dù đã chờ trạng thái sẵn sàng.")

        # SAU KHI CLICK RUN: Kiên nhẫn chờ Gemini phản hồi (tối đa 25 giây, kiểm tra mỗi 1 giây)
        # Giống hệt người dùng thật: sau khi bấm sẽ ngồi chờ máy chủ xử lý, KHÔNG bấm tiếp!
        step("Đã nhấn nút Run — đang chờ Gemini tiếp nhận video và bắt đầu sinh kịch bản...")
        wait_start = time.time()
        generating = False
        while time.time() - wait_start < 25:
            _check()
            page.wait_for_timeout(1000)

            if _is_generating(page, initial_turns):
                generating = True
                step("Đã xác nhận Gemini đang sinh kịch bản thành công.")
                return

            # Kiểm tra xem AI Studio có hiện lỗi không (cả alert lẫn chat turn)
            err_info = _detect_studio_error(page)
            if err_info:
                is_fatal, err_txt = err_info
                if is_fatal:
                    raise RuntimeError(f"AI Studio từ chối yêu cầu: {err_txt}")

                # Lỗi permission denied / failed to generate: do Google Cloud đang phân quyền video
                wait_retry_sec = 10 if ("permission" in err_txt.lower() or "failed to generate" in err_txt.lower()) else 5
                step(f"AI Studio báo sự cố tạm thời ({err_txt[:80]}...) — đợi {wait_retry_sec}s để Google Cloud hoàn tất phân quyền rồi bấm lại...")
                for sec_w in range(wait_retry_sec, 0, -2):
                    _check()
                    page.wait_for_timeout(2000)

                # Thử tìm nút Retry / Try again trên giao diện (nếu Google hiển thị nút Retry trên turn lỗi)
                try:
                    retry_btn = page.locator('button:has-text("Retry"), button:has-text("Try again"), button[aria-label*="Retry"]').last
                    if retry_btn.is_visible(timeout=1000):
                        step("Tìm thấy nút Retry của AI Studio — click nút Retry bằng chuột...")
                        _user_like_click(page, retry_btn, step)
                        page.wait_for_timeout(3000)
                        if _is_generating(page, initial_turns):
                            step("Đã kích hoạt lại thành công qua nút Retry.")
                            return
                except Exception:
                    pass

                break  # Thoát vòng chờ để attempt tiếp theo bấm lại nút Run

        if generating:
            return

        step(f"Chưa thấy Gemini sinh kịch bản sau lần {attempt} (đã đợi 25s) → thử lại...")
        page.wait_for_timeout(2000)

    if _is_generating(page, initial_turns):
        step("Gemini đã bắt đầu xử lý.")
        return

    raise RuntimeError("Không kích hoạt được Gemini sinh kịch bản sau các lần thử. Vui lòng kiểm tra cửa sổ Chrome.")


def _click_run(page, step):
    """B8 - Nhấn Run/Send bằng chuột (đợi nút khả dụng). TUYỆT ĐỐI không dùng Ctrl+Enter."""
    btn = _run_button(page)
    for _ in range(12):
        if _is_run_button_ready(btn):
            break
        page.wait_for_timeout(1000)
        btn = _run_button(page)

    if not _user_like_click(page, btn, step):
        btn.click(force=True)
    step("Đã nhấn Run bằng chuột.")


def _wait_user_submit(page, wait_sec, step, _check):
    """B8 - Chờ NGƯỜI DÙNG tự nhấn nút Run trong cửa sổ Chrome.
    Hệ thống chuẩn bị đầy đủ video + prompt, đưa cửa sổ Chrome lên màn hình,
    người dùng chỉ cần bấm 1 phát nút Run là pipeline tự động tiếp quản 100%."""
    _bring_chrome_to_foreground(step)
    try:
        page.bring_to_front()
        page.evaluate("window.focus()")
    except Exception:
        pass

    step("👉 VIDEO & PROMPT ĐÃ SẴN SÀNG! Xin mời bạn NHẤN NÚT RUN trong cửa sổ Chrome — chờ tối đa %.0fs." % max(wait_sec, 60))
    deadline = time.time() + max(wait_sec, 60)
    
    initial_turns = 0
    try:
        initial_turns = page.locator("ms-chat-turn").count()
    except Exception:
        initial_turns = 0

    while time.time() < deadline:
        _check()

        # 1. Phát hiện nút Run chuyển sang nút Stop (người dùng vừa bấm Run)
        if _is_stop_button_visible(page):
            step("✅ Nhận diện bạn đã bấm Run thành công (nút Stop đã xuất hiện) — hệ thống bắt đầu theo dõi kịch bản...")
            return

        # 2. Phát hiện model bắt đầu trả lời có text
        try:
            mt_text = _get_model_turn_text(page)
            if mt_text and len(mt_text.strip()) > 10 and "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in mt_text:
                step(f"✅ Nhận thấy Gemini bắt đầu sinh kịch bản ({len(mt_text)} ký tự) — tiếp tục pipeline...")
                return
        except Exception:
            pass

        # 3. Phát hiện số lượt chat turn tăng lên
        try:
            cur_turns = page.locator("ms-chat-turn").count()
            if cur_turns > initial_turns:
                step("✅ Nhận diện lượt chat mới đã được gửi — tiếp tục pipeline...")
                return
        except Exception:
            pass

        page.wait_for_timeout(800)
    raise RuntimeError("Hết thời gian chờ người dùng nhấn Run (quá thời hạn).")


def _scroll_to_bottom(page):
    page.evaluate("""() => {
        const chunks = document.querySelectorAll('ms-text-chunk');
        if (chunks.length) {
            const last = chunks[chunks.length - 1];
            last.scrollIntoView({ block: 'end', behavior: 'instant' });
            let parent = last.parentElement;
            while (parent) {
                if (parent.scrollHeight > parent.clientHeight) parent.scrollTop = parent.scrollHeight;
                parent = parent.parentElement;
            }
        }
    }""")


def _wait_response(page, timeout_sec, step, _check, max_retries=3):
    """B9+B10 - Theo dõi trạng thái, chờ response hoàn thành.
    - Đọc text từ TẤT CẢ ms-text-chunk của các turn model.
    - Nếu gặp lỗi: tự động gõ chữ 'tiếp' như người dùng bình thường và gửi lại bằng chuột (KHÔNG dùng Ctrl+Enter).
    - Nếu kịch bản bị ngắt giữa chừng: tự động gõ 'tiếp' để AI viết tiếp đầy đủ.
    """
    step("Theo dõi Gemini đang viết...")
    page.wait_for_timeout(2500)
    deadline = time.time() + timeout_sec
    last_len, stable = 0, 0
    text = ""
    retries = 0

    while time.time() < deadline:
        _check()
        _scroll_to_bottom(page)
        page.wait_for_timeout(1000)

        # Đọc text TỪ TẤT CẢ model turns (hỗ trợ nhiều lần gõ 'tiếp')
        text = _get_all_model_turns_text(page)

        # ── BƯỚC QUAN TRỌNG: Kiểm tra xem Gemini có đang sinh kịch bản không ──
        # Khi nút Stop đang hiển thị = Gemini đang trong quá trình generate.
        # TUYỆT ĐỐI không can thiệp (không click nút, không gõ chữ), reset stable=0.
        if _is_stop_button_visible(page):
            stable = 0
            last_len = len(text)
            step(f"Gemini đang sinh kịch bản... ({len(text)} ký tự — đang viết)")
            page.wait_for_timeout(1500)
            continue

        # ── Gemini ĐÃ DỪNG (Stop biến mất) — kiểm tra lỗi ──
        err_info = _detect_studio_error(page)
        if err_info:
            is_fatal, err_txt = err_info
            if is_fatal:
                raise RuntimeError(f"AI Studio báo lỗi nghiêm trọng: {err_txt}\n(Hãy kiểm tra tài khoản/model có quyền truy cập không.)")
            # Xử lý lỗi: tự động gõ chữ 'tiếp' và gửi lại bằng chuột
            if retries < max_retries:
                retries += 1
                step(f"AI Studio báo sự cố ({err_txt[:80]}...) (lần {retries}/{max_retries}) → gõ chữ 'tiếp' như người dùng bình thường và gửi lại bằng chuột...")
                page.wait_for_timeout(2000)

                _type_and_click_send(page, text="tiếp", step=step)

                wait_retry = 4 + retries * 2
                page.wait_for_timeout(wait_retry * 1000)
                _scroll_to_bottom(page)
                deadline = time.time() + timeout_sec
                last_len = len(_get_all_model_turns_text(page))
                stable = 0
                continue
            raise RuntimeError(f"Gemini liên tục báo lỗi ({err_txt[:100]}) — vui lòng thử lại sau.")

        # ── Stop không thấy, không có lỗi → đang chờ Gemini kết thúc ──
        # Chỉ xét hoàn thành khi text đã ổn định qua nhiều lần kiểm tra liên tiếp
        if len(text) > 0:
            if len(text) == last_len:
                stable += 1
                step(f"Text ổn định {stable}/3 ({len(text)} ký tự)...")
                if stable >= 3:
                    # Kiểm tra xem kịch bản đã đủ phân đoạn chưa
                    parsed = extract_script_from_text(text)
                    valid_lines = [l for l in parsed.splitlines() if l.strip()]
                    if len(valid_lines) < 5 and retries < max_retries:
                        retries += 1
                        step(f"Nội dung chưa đủ phân đoạn ({len(valid_lines)} dòng) (lần {retries}/{max_retries}) → gõ chữ 'tiếp' để AI viết tiếp...")
                        _type_and_click_send(page, text="tiếp", step=step)
                        deadline = time.time() + timeout_sec
                        stable = 0
                        last_len = len(text)
                        continue
                    step("Response hoàn thành.")
                    break
            else:
                # Text vẫn thay đổi → chưa xong
                stable = 0
                step(f"Gemini đang trả ({len(text)} ký tự)...")
        else:
            stable = 0
            step("Chờ Gemini bắt đầu trả lời...")
        last_len = len(text)

    if not text.strip():
        step("Không thu được text từ AI — text rỗng, có thể Chrome đã đóng/reset trước khi kịp đọc.")
        raise RuntimeError("Hết thời gian chờ, Gemini không trả response.")
    step(f"Đã thu response ({len(text.strip())} ký tự) — chuyển sang đọc/gọi pipeline.")
    return text


def _read_response(page, step):
    """B11 - Đọc response từ giao diện.
    Đọc trực tiếp từ ms-text-chunk của tất cả các turn model (chuẩn xác nhất)."""
    text = _get_all_model_turns_text(page)
    if text and len(text.strip()) > 100:
        step(f"Đã đọc response chuẩn từ model ({len(text)} ký tự).")
        return text.strip()

    single = _get_model_turn_text(page)
    if single and len(single.strip()) > 100:
        step(f"Đã đọc response từ turn model cuối ({len(single)} ký tự).")
        return single.strip()

    try:
        turns = page.locator("ms-chat-turn")
        n = turns.count()
        for back in range(n):
            t = turns.nth(n - 1 - back)
            chunks = t.locator("ms-text-chunk")
            if chunks.count():
                parts = []
                for i in range(chunks.count()):
                    pt = (chunks.nth(i).inner_text() or "").strip()
                    if pt:
                        parts.append(pt)
                combined = "\n".join(parts).strip()
                if combined and len(combined) > 100 and "XEM VÀ PHÂN TÍCH TOÀN BỘ VIDEO" not in combined:
                    step(f"Đã đọc response từ turn {n - 1 - back} ({len(combined)} ký tự).")
                    return combined
    except Exception:
        pass

    return ""


def run_ai_studio_auto(prompt, video_path, timeout_sec=450, output_write=None,
                       is_cancelled=None, model=None, wait_user_submit=True):
    """Chạy đủ 12 bước tự động hóa AI Studio trên Chrome automation, trả về kịch bản.

    - video_path: video nén (height=480/fps=24) gửi AI Studio.
    - is_cancelled: callback trả True thì dừng ngay.
    - model: tên model muốn đặt trong UI (best-effort).
    - wait_user_submit: True → đợi NGƯỜI DÙNG nhấn Run (tạm thời, để né lỗi 권 gửi),
      False → tự nhấn Run.
    """
    def step(msg):
        logger.info("AIStudio: %s", msg)
        if output_write:
            try:
                output_write(msg)
            except Exception:
                pass

    def _check():
        if is_cancelled and is_cancelled():
            raise RuntimeError('__CANCELLED__')

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video nén không tồn tại: {video_path}")

    with _AUTOMATION_LOCK:
        step(f"B1: Mở/kết nối Google Chrome thật (profile '{_chrome_profile()}')...")
        last_err = None
        for attempt in (0, 1):
            try:
                fresh = _launch_automation_chrome(step)
                _check()
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(f"http://{CDP_HOST}:{CDP_PORT}")
                    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                    try:
                        ctx.grant_permissions(["clipboard-read", "clipboard-write"],
                                              origin="https://aistudio.google.com")
                    except Exception:
                        pass
                    # Tái dùng TAB AI STUDIO CÓ SẴN (tab mới tạo qua CDP hay bị crash
                    # chrome-error / TargetClosedError — nhất là giữa lúc upload file).
                    # Chỉ tạo tab mới khi chưa có tab aistudio nào.
                    page = None
                    for pg in ctx.pages:
                        try:
                            if "aistudio.google.com" in pg.url:
                                page = pg
                                break
                        except Exception:
                            pass
                    page = page if page is not None else ctx.new_page()
                    # Dọn các tab aistudio khác (không tích lũy tab thừa giữa các lần chạy).
                    for pg in list(ctx.pages):
                        try:
                            if pg is not page and "aistudio.google.com" in pg.url:
                                pg.close()
                        except Exception:
                            pass
                    try:
                        page.goto(AI_STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(4000)
                        _check()
                        _ensure_logged_in(page, step, _check)

                        step("B2: Chọn workspace — conversation Prompt mới...")
                        # Thử tạo prompt mới qua nút giao diện hoặc reload sạch
                        try:
                            new_p = page.locator('button:has-text("Create prompt"), button:has-text("New prompt")').first
                            if new_p.is_visible(timeout=2000):
                                new_p.click()
                                page.wait_for_timeout(2000)
                            else:
                                page.goto(AI_STUDIO_URL, wait_until="domcontentloaded", timeout=60000)
                        except Exception:
                            page.goto(AI_STUDIO_URL, wait_until="domcontentloaded", timeout=60000)

                        page.locator("ms-prompt-editor, textarea").first.wait_for(state="visible", timeout=30000)

                        # Đảm bảo sidebar cấu hình bên phải luôn mở (không bao giờ click nhầm nút Close sidebar)
                        try:
                            # Nếu sidebar bị đóng (có nút mở Tune/Settings), bấm mở lại
                            tune_btn = page.locator('button[aria-label*="Tune"], button[aria-label*="Model settings"]').first
                            if tune_btn.is_visible(timeout=1000):
                                tune_btn.click()
                                page.wait_for_timeout(500)
                        except Exception:
                            pass
                        _check()

                        step("B3: Chọn model...")
                        _select_model(page, model, step)
                        _check()

                        step("B4: Chọn chế độ...")
                        _set_thinking_level(page, step)
                        _check()

                        step("B5: Upload video...")
                        _upload_file(page, video_path, step, _check)
                        _check()

                        step("B6: Điền prompt (song song lúc video index)...")
                        _fill_prompt(page, prompt, step, _check)
                        _check()

                        step("B7: Chờ xử lý/index video...")
                        _wait_processing(page, step, _check)
                        _check()

                        if wait_user_submit:
                            step("B8: Chờ người dùng nhấn Run trong cửa sổ Chrome...")
                            _wait_user_submit(page, timeout_sec, step, _check)
                            max_retries = 0
                        else:
                            step("B8: Tự động gửi prompt và kích hoạt Run...")
                            _auto_submit(page, step, _check)
                            max_retries = 3
                        _check()

                        step("B9/B10: Theo dõi Gemini, chờ response hoàn thành...")
                        stream_text = _wait_response(page, timeout_sec, step, _check, max_retries=max_retries)

                        step("B11: Đọc response từ giao diện...")
                        raw = stream_text.strip() if (stream_text and len(stream_text.strip()) > 100) else _read_response(page, step)
                        script = extract_script_from_text(raw)
                        if not script or len([l for l in script.splitlines() if l.strip()]) < 5:
                            script = extract_script_from_text(_read_response(page, step)) or extract_script_from_text(stream_text)
                        if not script or len([l for l in script.splitlines() if l.strip()]) < 5:
                            raise RuntimeError(f"Không thu được kịch bản có timestamp từ Gemini (thu được: {raw[:150]}...). Vui lòng kiểm tra lại phản hồi từ AI Studio.")

                        step(f"B12: Hoàn tất — trả {len([l for l in script.splitlines() if l.strip()])} "
                             f"phân đoạn cho backend.")
                        return script
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
            except Exception as e:
                import traceback
                step("LỖI lấy kết quả AI Studio: %s" % e)
                step("TRACEBACK:\n" + traceback.format_exc())
                if type(e).__name__ == 'TargetClosedError' and attempt == 0:
                    step("Cửa sổ/tab Chrome bị đóng giữa chừng — thử lại lần 2...")
                    last_err = e
                    continue
                raise
        raise (last_err or RuntimeError("Không hoàn thành được luồng AI Studio."))