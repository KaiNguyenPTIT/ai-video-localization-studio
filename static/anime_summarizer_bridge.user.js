// ==UserScript==
// @name         Anime Summarizer AI Studio Bridge
// @namespace    http://localhost:8000/
// @version      1.0
// @description  Tự động hóa kết nối Google AI Studio với công cụ Anime Summarizer
// @author       Antigravity
// @match        https://aistudio.google.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      localhost
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    const BACKEND_URL = 'http://localhost:8000';
    let isProcessing = false;
    let currentTaskId = null;

    // 1. Tạo thanh trạng thái nổi (Floating Status Badge)
    const badge = document.createElement('div');
    badge.id = 'anime-bridge-badge';
    badge.style.position = 'fixed';
    badge.style.top = '12px';
    badge.style.right = '120px';
    badge.style.zIndex = '999999';
    badge.style.backgroundColor = '#1a1a24';
    badge.style.color = '#e2e8f0';
    badge.style.padding = '8px 14px';
    badge.style.borderRadius = '8px';
    badge.style.fontSize = '13px';
    badge.style.fontWeight = '500';
    badge.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
    badge.style.border = '1px solid #4f46e5';
    badge.style.display = 'flex';
    badge.style.alignItems = 'center';
    badge.style.gap = '8px';
    badge.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    badge.innerHTML = '<span style="color:#22c55e">●</span> Anime Bridge: Sẵn sàng';
    document.body.appendChild(badge);

    function updateBadge(text, color = '#38bdf8') {
        badge.innerHTML = `<span style="color:${color}">●</span> ${text}`;
    }

    function reportStatus(msg) {
        if (!currentTaskId) return;
        try {
            const fd = new FormData();
            fd.append('task_id', currentTaskId);
            fd.append('message', msg);
            fetch(`${BACKEND_URL}/api/bridge/update-status`, { method: 'POST', body: fd }).catch(() => {});
        } catch (e) {}
    }

    function completeTask(resultText) {
        if (!currentTaskId) return;
        const fd = new FormData();
        fd.append('task_id', currentTaskId);
        fd.append('result_text', resultText);
        fetch(`${BACKEND_URL}/api/bridge/complete-task`, { method: 'POST', body: fd })
            .then(res => res.json())
            .then(() => {
                updateBadge('✅ Đã gửi kịch bản về App thành công!', '#22c55e');
                reportStatus('Đã nhận kịch bản từ AI Studio. Đang tiến hành tạo video...');
                setTimeout(() => {
                    isProcessing = false;
                    currentTaskId = null;
                    updateBadge('Anime Bridge: Sẵn sàng', '#22c55e');
                }, 5000);
            })
            .catch(err => {
                updateBadge('❌ Lỗi gửi kết quả về App', '#ef4444');
                isProcessing = false;
            });
    }

    // 2. Hàm trích xuất kịch bản có timestamp từ DOM
    function extractScriptText() {
        const lineRe = /^\s*(\d{1,2}:\d{2}:\d{2})[\t ]+(.+)$/gm;
        // Đọc từ các chunks hoặc body
        let allText = '';
        const chunks = document.querySelectorAll('ms-text-chunk');
        if (chunks.length > 0) {
            chunks.forEach(c => allText += '\n' + (c.innerText || ''));
        } else {
            allText = document.body.innerText || '';
        }

        const matches = [];
        let m;
        while ((m = lineRe.exec(allText)) !== null) {
            matches.push(`${m[1]}\t${m[2].trim()}`);
        }
        return matches.join('\n');
    }

    // 3. Thực thi Task trên AI Studio
    async function processTask(task) {
        isProcessing = true;
        currentTaskId = task.id;
        updateBadge(`⏳ Đang xử lý task ${task.id}...`, '#f59e0b');
        reportStatus('Userscript đang kết nối và nạp dữ liệu vào AI Studio...');

        try {
            // A. Tìm ô nhập prompt
            let textarea = document.querySelector('textarea.cdk-textarea-autosize, textarea, div[contenteditable="true"]');
            let tries = 0;
            while (!textarea && tries < 20) {
                await new Promise(r => setTimeout(r, 500));
                textarea = document.querySelector('textarea.cdk-textarea-autosize, textarea, div[contenteditable="true"]');
                tries++;
            }

            if (!textarea) {
                throw new Error('Không tìm thấy ô nhập prompt trên AI Studio');
            }

            // B. Tải video blob từ Localhost
            updateBadge('📥 Đang nạp video nén...', '#38bdf8');
            reportStatus('Đang nạp file video nén vào AI Studio...');
            const videoUrl = `${BACKEND_URL}${task.video_url}`;
            const videoRes = await fetch(videoUrl);
            const videoBlob = await videoRes.blob();
            const videoFile = new File([videoBlob], task.video_name || 'compressed_anime.mp4', { type: 'video/mp4' });

            // C. Đính kèm video vào AI Studio
            let fileInput = document.querySelector('input[type="file"]');
            if (!fileInput) {
                // Thử bấm nút Add Media để mở input
                const addBtn = document.querySelector('button[data-test-id="add-media-button"], button[aria-label*="Add"], button[aria-label*="media"]');
                if (addBtn) {
                    addBtn.click();
                    await new Promise(r => setTimeout(r, 600));
                    fileInput = document.querySelector('input[type="file"]');
                }
            }

            if (fileInput) {
                const dt = new DataTransfer();
                dt.items.add(videoFile);
                fileInput.files = dt.files;
                fileInput.dispatchEvent(new Event('change', { bubbles: true }));
                fileInput.dispatchEvent(new Event('input', { bubbles: true }));
            } else {
                // Drop event fallback
                const dt = new DataTransfer();
                dt.items.add(videoFile);
                const dropTarget = textarea.closest('.input-area, form, main') || textarea;
                dropTarget.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
            }

            updateBadge('⏳ Chờ AI Studio xử lý video...', '#38bdf8');
            reportStatus('Đang chờ AI Studio xử lý và index video (10s)...');
            await new Promise(r => setTimeout(r, 10000));

            // D. Gán Prompt vào textarea
            updateBadge('✍️ Đang dán prompt...', '#38bdf8');
            textarea.focus();
            if (textarea.tagName.toLowerCase() === 'textarea') {
                textarea.value = task.prompt;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
            } else {
                textarea.innerText = task.prompt;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
            }
            await new Promise(r => setTimeout(r, 1000));

            // E. Tìm và bấm nút Run
            updateBadge('🚀 Bấm Run...', '#38bdf8');
            reportStatus('Đã gửi yêu cầu. Chờ Gemini viết kịch bản...');
            let runBtn = document.querySelector('button[aria-label*="Run cell"], button[data-test-id="run-button"]');
            if (!runBtn) {
                const buttons = Array.from(document.querySelectorAll('button'));
                runBtn = buttons.find(b => b.innerText.includes('Run'));
            }

            if (runBtn) {
                runBtn.click();
            } else {
                // Fallback Ctrl + Enter
                textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', ctrlKey: true, bubbles: true }));
            }

            // F. Lắng nghe và chờ kết quả
            updateBadge('🧠 Gemini đang viết kịch bản...', '#8b5cf6');
            let lastScript = '';
            let stableCount = 0;
            const maxWait = 360; // 6 phút tối đa
            let elapsed = 0;

            const checkInterval = setInterval(() => {
                elapsed += 3;
                const script = extractScriptText();
                const lines = script.split('\n').filter(l => l.trim().length > 0);

                if (lines.length >= 2) {
                    updateBadge(`✍️ AI đã viết được ${lines.length} phân đoạn...`, '#8b5cf6');
                    reportStatus(`AI Studio đang viết kịch bản (đã nhận ${lines.length} phân đoạn)...`);
                    if (script === lastScript) {
                        stableCount++;
                        if (stableCount >= 2) { // 6 giây không đổi -> Hoàn thành
                            clearInterval(checkInterval);
                            completeTask(script);
                        }
                    } else {
                        lastScript = script;
                        stableCount = 0;
                    }
                }

                if (elapsed >= maxWait) {
                    clearInterval(checkInterval);
                    if (lastScript) {
                        completeTask(lastScript);
                    } else {
                        updateBadge('❌ Timeout chờ AI trả lời', '#ef4444');
                        isProcessing = false;
                    }
                }
            }, 3000);

        } catch (err) {
            console.error('Anime Bridge error:', err);
            updateBadge(`❌ Lỗi: ${err.message}`, '#ef4444');
            isProcessing = false;
        }
    }

    // 4. Polling kiểm tra task từ Backend
    setInterval(async () => {
        if (isProcessing) return;
        try {
            const res = await fetch(`${BACKEND_URL}/api/bridge/pending-task`).catch(() => null);
            if (!res || !res.ok) return;
            const data = await res.json();
            if (data && data.task && data.task.id) {
                processTask(data.task);
            }
        } catch (e) {}
    }, 2000);

})();
