import { useCallback, useEffect, useState } from 'react';
import { adminService, type AdminSettingSchema } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './TuningPanel.module.css';

const GROUP_ORDER: { id: string; title: string; desc: string }[] = [
  { id: 'encoding', title: 'Mã Hóa Video Đầu Ra', desc: 'Độ phân giải, bitrate, GOP — quyết định chất lượng và dung lượng file thành phẩm.' },
  { id: 'smart_shot', title: 'Dựng Cảnh Thông Minh', desc: 'Phát hiện shot, chọn cảnh, 4 hiệu ứng dựng (lật/zoom/tốc độ/ngược) và giới hạn RAM.' },
  { id: 'tts', title: 'Kịch Bản & Giọng Đọc', desc: 'Nhịp độ lời bình, số phân đoạn và model AI viết kịch bản.' },
  { id: 'concurrency', title: 'Xử Lý Song Song', desc: 'Số tập chạy đồng thời — tăng tốc nhưng tốn RAM/CPU.' },
];

type Values = Record<string, unknown>;

interface Preset {
  label: string;
  value: unknown;
  /** Mô tả ngắn hiện dưới cụm lựa chọn khi đang chọn mục này */
  desc?: string;
}

/** Lựa chọn đặt sẵn cho mọi thông số dạng số/chuỗi — thay ô nhập số khó hiểu.
 *  Giá trị "mặc định" lấy từ schema backend lúc render (đánh dấu ★), không hardcode. */
const PRESETS: Record<string, Preset[]> = {
  OUTPUT_FPS: [
    { label: 'Điện ảnh 24', value: 24 },
    { label: 'Chuẩn 30', value: 30 },
    { label: 'Mượt 60', value: 60 },
  ],
  OUTPUT_VIDEO_BITRATE: [
    { label: 'Tiết kiệm 4M', value: '4M' },
    { label: 'Cân bằng 5M', value: '5M' },
    { label: 'Cao 8M', value: '8M' },
    { label: 'Tối đa 12M', value: '12M' },
  ],
  OUTPUT_VIDEO_MAXRATE: [
    { label: 'Trần 6M', value: '6M' },
    { label: 'Trần 8M', value: '8M' },
    { label: 'Trần 12M', value: '12M' },
  ],
  OUTPUT_VIDEO_CQ: [
    { label: 'Nét 22', value: 22 },
    { label: 'Cân bằng 26', value: 26 },
    { label: 'Nhẹ 30', value: 30 },
  ],
  OUTPUT_NVENC_PRESET: [
    { label: 'Nhanh p1', value: 'p1' },
    { label: 'Cân bằng p4', value: 'p4' },
    { label: 'Nén tốt p7', value: 'p7' },
  ],
  OUTPUT_GOP_SECONDS: [
    { label: 'Tua mượt 1s', value: 1 },
    { label: 'Chuẩn 2s', value: 2 },
    { label: 'Nén tốt 4s', value: 4 },
  ],
  OUTPUT_AUDIO_BITRATE: [
    { label: '128k', value: '128k' },
    { label: '192k', value: '192k' },
    { label: '320k', value: '320k' },
  ],
  OUTPUT_AUDIO_RATE: [
    { label: '44100 Hz', value: 44100 },
    { label: '48000 Hz', value: 48000 },
  ],
  SHOT_SCENE_THRESHOLD: [
    { label: 'Nhạy', value: 0.1 },
    { label: 'Chuẩn', value: 0.2 },
    { label: 'Ít nhạy', value: 0.35 },
  ],
  PYSCENE_ADAPTIVE_THRESHOLD: [
    { label: 'Nhạy', value: 1.5 },
    { label: 'Chuẩn', value: 3.0 },
    { label: 'Chắc', value: 6.0 },
  ],
  PYSCENE_MIN_CONTENT_VAL: [
    { label: '10', value: 10.0 },
    { label: '15', value: 15.0 },
    { label: '25', value: 25.0 },
  ],
  PYSCENE_CONTENT_THRESHOLD: [
    { label: '20', value: 20.0 },
    { label: '27', value: 27.0 },
    { label: '35', value: 35.0 },
  ],
  PYSCENE_MIN_SCENE_LEN: [
    { label: '0.3s', value: 0.3 },
    { label: '0.4s', value: 0.4 },
    { label: '0.8s', value: 0.8 },
  ],
  SHOT_MERGE_MIN: [
    { label: 'Giữ chi tiết', value: 0.3 },
    { label: 'Chuẩn', value: 0.5 },
    { label: 'Gộp mạnh', value: 1.0 },
  ],
  SHOT_MIN_DURATION: [
    { label: '0.5s', value: 0.5 },
    { label: '0.8s', value: 0.8 },
    { label: '1.5s', value: 1.5 },
  ],
  SHOT_MAX_DURATION: [
    { label: 'Ngắn 5s', value: 5.0 },
    { label: 'Chuẩn 8s', value: 8.0 },
    { label: 'Dài 15s', value: 15.0 },
  ],
  SEARCH_WINDOW_BEFORE: [
    { label: '3s', value: 3.0 },
    { label: '6s', value: 6.0 },
    { label: '10s', value: 10.0 },
  ],
  SEARCH_WINDOW_AFTER: [
    { label: '5s', value: 5.0 },
    { label: '8s', value: 8.0 },
    { label: '12s', value: 12.0 },
  ],
  MIN_CLIP_DURATION: [
    { label: '0.5s', value: 0.5 },
    { label: '0.8s', value: 0.8 },
    { label: '1.2s', value: 1.2 },
  ],
  MAX_CLIP_DURATION: [
    { label: '4s', value: 4.0 },
    { label: '6s', value: 6.0 },
    { label: '10s', value: 10.0 },
  ],
  MAX_REUSE_DISTANCE: [
    { label: '15s', value: 15.0 },
    { label: '30s', value: 30.0 },
    { label: '60s', value: 60.0 },
  ],
  VOICE_SYNC_TOLERANCE: [
    { label: 'Khít', value: 0.15 },
    { label: 'Chuẩn', value: 0.25 },
    { label: 'Thoáng', value: 0.5 },
  ],
  SMART_SHOT_ZOOM_PERCENT: [
    { label: 'Tắt zoom', value: 100.0 },
    { label: 'Nhẹ', value: 115.0 },
    { label: 'Vừa', value: 125.0 },
    { label: 'Mạnh', value: 150.0 },
  ],
  SMART_SHOT_SPEED_MIN: [
    { label: 'Chuẩn 1.0', value: 1.0 },
    { label: '1.1', value: 1.1 },
    { label: '1.25', value: 1.25 },
  ],
  SMART_SHOT_SPEED_MAX: [
    { label: 'Tắt tăng tốc', value: 1.0 },
    { label: 'Nhẹ', value: 1.25 },
    { label: 'Vừa', value: 1.5 },
    { label: 'Mạnh', value: 2.0 },
  ],
  SHOT_REVERSE_MAX_SEC: [
    { label: '1.5s', value: 1.5 },
    { label: '2.0s', value: 2.0 },
    { label: '3.0s', value: 3.0 },
  ],
  REVERSE_CHUNK_SEC: [
    { label: 'Nhẹ RAM', value: 3.0 },
    { label: 'Cân bằng', value: 5.0 },
    { label: 'Ít khúc nối', value: 8.0 },
  ],
  INTRO_SKIP_SECONDS: [
    { label: 'Không bỏ', value: 0.0 },
    { label: '30s', value: 30.0 },
    { label: '60s', value: 60.0 },
    { label: '90s', value: 90.0 },
  ],
  OUTRO_SKIP_SECONDS: [
    { label: 'Không bỏ', value: 0.0 },
    { label: '30s', value: 30.0 },
    { label: '60s', value: 60.0 },
    { label: '90s', value: 90.0 },
  ],
  WORDS_PER_MINUTE: [
    { label: 'Chậm rãi', value: 240.0 },
    { label: 'Chuẩn', value: 277.0 },
    { label: 'Nhanh', value: 320.0 },
  ],
  SEGMENTS_PER_MINUTE: [
    { label: '5', value: 5.0 },
    { label: '6.67', value: 6.67 },
    { label: '8', value: 8.0 },
  ],
  MAX_NETWORK_EPISODES: [
    { label: '1', value: 1 },
    { label: '2', value: 2 },
    { label: '4', value: 4 },
  ],
  MAX_INFLIGHT_EPISODES: [
    { label: '3', value: 3 },
    { label: '6', value: 6 },
    { label: '10', value: 10 },
  ],
};

/** Mô tả từng lựa chọn — hiện dưới cụm nút khi đang chọn. Key: "TEN_KEY::gia_tri". */
const PRESET_HINTS: Record<string, string> = {
  'OUTPUT_FPS::24': 'Kiểu phim điện ảnh, file nhẹ hơn.',
  'OUTPUT_FPS::30': 'Chuẩn YouTube, hợp hầu hết video.',
  'OUTPUT_FPS::60': 'Siêu mượt nhưng file nặng, dựng lâu hơn.',
  'OUTPUT_VIDEO_BITRATE::4M': 'File nhẹ, xem tốt trên điện thoại.',
  'OUTPUT_VIDEO_BITRATE::5M': 'Mức cân bằng mới (VBR): nét gần nguyên, nhẹ hơn CBR 8M cũ ~40%.',
  'OUTPUT_VIDEO_BITRATE::8M': 'Nét cao, file lớn hơn rõ rệt.',
  'OUTPUT_VIDEO_BITRATE::12M': 'Nét tối đa, file rất lớn.',
  'OUTPUT_VIDEO_MAXRATE::6M': 'Trần thấp: file nhẹ nhất, cảnh hành động có thể hơi mờ.',
  'OUTPUT_VIDEO_MAXRATE::8M': 'Trần cân bằng: giữ đỉnh cảnh hành động.',
  'OUTPUT_VIDEO_MAXRATE::12M': 'Trần cao: giữ chi tiết tối đa khi chuyển động nhanh.',
  'OUTPUT_VIDEO_CQ::22': 'Nét cao, file lớn hơn.',
  'OUTPUT_VIDEO_CQ::26': 'Cân bằng: mắt thường khó phân biệt với CBR 8M cũ.',
  'OUTPUT_VIDEO_CQ::30': 'File nhẹ nhất, vùng chuyển động nhanh hơi mờ.',
  'OUTPUT_NVENC_PRESET::p1': 'Encode nhanh nhất, file lớn nhất.',
  'OUTPUT_NVENC_PRESET::p4': 'Cân bằng: chậm hơn p1 ~10% nhưng nhẹ hơn ~20-30%.',
  'OUTPUT_NVENC_PRESET::p7': 'Nén tốt nhất, encode chậm nhất.',
  'OUTPUT_GOP_SECONDS::1': 'Tua video chuẩn từng giây.',
  'OUTPUT_GOP_SECONDS::2': 'Cân bằng giữa tua chuẩn và dung lượng.',
  'OUTPUT_GOP_SECONDS::4': 'File nhẹ hơn, tua kém chính xác hơn.',
  'OUTPUT_AUDIO_BITRATE::128k': 'Nghe rõ, file nhẹ.',
  'OUTPUT_AUDIO_BITRATE::192k': 'Chuẩn nghe tốt.',
  'OUTPUT_AUDIO_BITRATE::320k': 'Tiếng hay nhất, file lớn hơn.',
  'OUTPUT_AUDIO_RATE::44100': 'Chuẩn của nhạc số.',
  'OUTPUT_AUDIO_RATE::48000': 'Chuẩn của video.',
  'EDIT_MODE_DEFAULT::legacy': 'Cắt chia đôi đơn giản, dựng nhanh nhất.',
  'EDIT_MODE_DEFAULT::smart_shot': 'Khớp shot theo lời bình kèm hiệu ứng, đẹp hơn.',
  'SHOT_DETECTOR::auto': 'Tự dùng cái tốt nhất đang có.',
  'SHOT_DETECTOR::ffmpeg': 'Nhẹ, luôn có sẵn.',
  'SHOT_DETECTOR::pyscenedetect': 'Chuẩn xác hơn, tốn RAM hơn.',
  'PYSCENE_METHOD::adaptive': 'Tự thích nghi theo video, hợp anime.',
  'PYSCENE_METHOD::content': 'So sánh nội dung thuần túy.',
  'SHOT_SCENE_THRESHOLD::0.1': 'Bắt được cả chuyển cảnh rất nhẹ, dễ cắt vụn.',
  'SHOT_SCENE_THRESHOLD::0.2': 'Mức nhạy vừa phải.',
  'SHOT_SCENE_THRESHOLD::0.35': 'Chỉ cắt khi chuyển cảnh rõ rệt.',
  'PYSCENE_ADAPTIVE_THRESHOLD::1.5': 'Rất nhạy, nhiều shot nhỏ.',
  'PYSCENE_ADAPTIVE_THRESHOLD::3': 'Mức vừa phải.',
  'PYSCENE_ADAPTIVE_THRESHOLD::6': 'Chỉ tách khi khác biệt lớn.',
  'PYSCENE_MIN_CONTENT_VAL::10': 'Dễ tính là cảnh mới.',
  'PYSCENE_MIN_CONTENT_VAL::15': 'Mức vừa phải.',
  'PYSCENE_MIN_CONTENT_VAL::25': 'Khó tính, ít cảnh hơn.',
  'PYSCENE_CONTENT_THRESHOLD::20': 'Dễ tách cảnh.',
  'PYSCENE_CONTENT_THRESHOLD::27': 'Mức vừa phải.',
  'PYSCENE_CONTENT_THRESHOLD::35': 'Ít tách cảnh hơn.',
  'PYSCENE_MIN_SCENE_LEN::0.3': 'Giữ lại cả cảnh chớp nhoáng.',
  'PYSCENE_MIN_SCENE_LEN::0.4': 'Mức vừa phải.',
  'PYSCENE_MIN_SCENE_LEN::0.8': 'Bỏ qua cảnh quá ngắn.',
  'SHOT_MERGE_MIN::0.3': 'Giữ lại shot chớp sáng.',
  'SHOT_MERGE_MIN::0.5': 'Gộp shot vụn vào shot trước.',
  'SHOT_MERGE_MIN::1': 'Gộp mạnh tay, ít shot hơn.',
  'SHOT_MIN_DURATION::0.5': 'Giữ shot từ nửa giây.',
  'SHOT_MIN_DURATION::0.8': 'Bỏ shot ngắn hơn 0.8 giây.',
  'SHOT_MIN_DURATION::1.5': 'Chỉ giữ shot dài, ít cảnh.',
  'SHOT_MAX_DURATION::5': 'Cảnh ngắn, nhịp dồn dập.',
  'SHOT_MAX_DURATION::8': 'Độ dài cảnh vừa phải.',
  'SHOT_MAX_DURATION::15': 'Cho phép cảnh dài, chậm rãi.',
  'SEARCH_WINDOW_BEFORE::3': 'Tìm hẹp trước mốc giờ — nhanh.',
  'SEARCH_WINDOW_BEFORE::6': 'Phạm vi vừa phải.',
  'SEARCH_WINDOW_BEFORE::10': 'Tìm rộng — khớp chuẩn hơn, chậm hơn.',
  'SEARCH_WINDOW_AFTER::5': 'Tìm hẹp sau mốc giờ — nhanh.',
  'SEARCH_WINDOW_AFTER::8': 'Phạm vi vừa phải.',
  'SEARCH_WINDOW_AFTER::12': 'Tìm rộng — khớp chuẩn hơn, chậm hơn.',
  'MIN_CLIP_DURATION::0.5': 'Giữ mảnh clip từ nửa giây.',
  'MIN_CLIP_DURATION::0.8': 'Loại mảnh clip quá ngắn.',
  'MIN_CLIP_DURATION::1.2': 'Chỉ giữ mảnh clip đủ dài.',
  'MAX_CLIP_DURATION::4': 'Cảnh ngắn, nhịp nhanh.',
  'MAX_CLIP_DURATION::6': 'Độ dài vừa phải.',
  'MAX_CLIP_DURATION::10': 'Cho phép cảnh dài.',
  'MAX_REUSE_DISTANCE::15': 'Shot lặp lại sau 15 giây mới được dùng lại.',
  'MAX_REUSE_DISTANCE::30': 'Chống lặp hình trong 30 giây.',
  'MAX_REUSE_DISTANCE::60': 'Chống lặp hình trong 1 phút.',
  'VOICE_SYNC_TOLERANCE::0.15': 'Khớp hình với lời bình rất khít.',
  'VOICE_SYNC_TOLERANCE::0.25': 'Sai số vừa phải.',
  'VOICE_SYNC_TOLERANCE::0.5': 'Thoáng, dễ khớp cảnh hơn.',
  'SMART_SHOT_ZOOM_PERCENT::100': 'Tắt zoom, giữ nguyên khung hình.',
  'SMART_SHOT_ZOOM_PERCENT::115': 'Zoom nhẹ, ít chóng mặt.',
  'SMART_SHOT_ZOOM_PERCENT::125': 'Zoom vừa, có chiều sâu.',
  'SMART_SHOT_ZOOM_PERCENT::150': 'Zoom sâu, hiệu ứng mạnh.',
  'SMART_SHOT_SPEED_MIN::1': 'Tốc độ thấp nhất là phát thường.',
  'SMART_SHOT_SPEED_MIN::1.1': 'Cảnh chậm nhất cũng nhanh hơn chút.',
  'SMART_SHOT_SPEED_MIN::1.25': 'Mọi cảnh đều tua nhanh ít nhất 1.25 lần.',
  'SMART_SHOT_SPEED_MAX::1': 'Tắt tăng tốc hoàn toàn.',
  'SMART_SHOT_SPEED_MAX::1.25': 'Nhanh nhẹ, khó nhận ra.',
  'SMART_SHOT_SPEED_MAX::1.5': 'Nhanh vừa, nhịp recap chuẩn.',
  'SMART_SHOT_SPEED_MAX::2': 'Rất nhanh, dồn dập.',
  'SHOT_REVERSE_MAX_SEC::1.5': 'Chỉ đảo shot rất ngắn.',
  'SHOT_REVERSE_MAX_SEC::2': 'Đảo shot ngắn tới 2 giây.',
  'SHOT_REVERSE_MAX_SEC::3': 'Đảo cả shot dài tới 3 giây.',
  'REVERSE_CHUNK_SEC::3': 'An toàn RAM nhất, nhiều mối nối hơn.',
  'REVERSE_CHUNK_SEC::5': 'Cân bằng RAM và tốc độ.',
  'REVERSE_CHUNK_SEC::8': 'Ít mối nối hơn, tốn RAM hơn.',
  'INTRO_SKIP_SECONDS::0': 'Giữ nguyên đầu video.',
  'INTRO_SKIP_SECONDS::30': 'Bỏ 30 giây đầu (thường là nhạc mở đầu).',
  'INTRO_SKIP_SECONDS::60': 'Bỏ 1 phút đầu.',
  'INTRO_SKIP_SECONDS::90': 'Bỏ 1 phút rưỡi đầu.',
  'OUTRO_SKIP_SECONDS::0': 'Giữ nguyên cuối video.',
  'OUTRO_SKIP_SECONDS::30': 'Bỏ 30 giây cuối (thường là nhạc kết).',
  'OUTRO_SKIP_SECONDS::60': 'Bỏ 1 phút cuối.',
  'OUTRO_SKIP_SECONDS::90': 'Bỏ 1 phút rưỡi cuối.',
  'WORDS_PER_MINUTE::240': 'Giọng đọc chậm rãi, video dài hơn.',
  'WORDS_PER_MINUTE::277': 'Nhịp đọc vừa phải.',
  'WORDS_PER_MINUTE::320': 'Đọc nhanh, video gọn hơn.',
  'SEGMENTS_PER_MINUTE::5': 'Ít phân cảnh, mỗi cảnh dài.',
  'SEGMENTS_PER_MINUTE::6.67': 'Mật độ vừa phải.',
  'SEGMENTS_PER_MINUTE::8': 'Nhiều phân cảnh ngắn, chi tiết.',
  'MAX_NETWORK_EPISODES::1': 'Gọi AI từng tập một — chậm mà chắc.',
  'MAX_NETWORK_EPISODES::2': 'Mức vừa phải.',
  'MAX_NETWORK_EPISODES::4': 'Gọi AI 4 tập cùng lúc — nhanh nhất.',
  'MAX_INFLIGHT_EPISODES::3': 'Nhẹ RAM nhất.',
  'MAX_INFLIGHT_EPISODES::6': 'Mức vừa phải.',
  'MAX_INFLIGHT_EPISODES::10': 'Nhanh nhất, tốn RAM nhất.',
  'CHARACTER_NAME_MODE::vietnamese': 'Lời bình chỉ dùng tên tiếng Việt (Việt hóa), không xen tên gốc Kanji/Romaji.',
  'CHARACTER_NAME_MODE::romaji': 'Lời bình giữ tên gốc Latin hóa (Jin, Sakura), không dịch sang tiếng Việt.',
};

/** Mô tả từng mục cài đặt bằng tiếng Việt phổ thông. */
const SETTING_DESC: Record<string, string> = {
  OUTPUT_FPS: 'Số khung hình mỗi giây của video thành phẩm.',
  OUTPUT_VIDEO_BITRATE: 'Độ nét mục tiêu của hình ảnh (VBR). Cao thì nét nhưng file lớn.',
  OUTPUT_VIDEO_MAXRATE: 'Trần bitrate VBR: giới hạn đỉnh khi cảnh hành động phức tạp.',
  OUTPUT_VIDEO_CQ: 'Ngưỡng chất lượng NVENC (càng nhỏ càng nét, 26 là cân bằng).',
  OUTPUT_NVENC_PRESET: 'Preset encode GPU: p1 nhanh nhất, p7 nén tốt nhất, p4 cân bằng.',
  OUTPUT_GOP_SECONDS: 'Khoảng cách giữa các khung hình chuẩn. Ngắn thì tua video chính xác hơn.',
  OUTPUT_AUDIO_BITRATE: 'Độ nét của tiếng thuyết minh.',
  OUTPUT_AUDIO_RATE: 'Tần số mẫu của tiếng. 48000 Hz là chuẩn video.',
  EDIT_MODE_DEFAULT: 'Cách dựng mặc định cho video mới làm.',
  SHOT_SCENE_THRESHOLD: 'Độ nhạy phát hiện chuyển cảnh.',
  SHOT_DETECTOR: 'Công cụ cắt cảnh. Auto tự chọn cái tốt nhất.',
  PYSCENE_METHOD: 'Thuật toán cắt cảnh của PySceneDetect.',
  PYSCENE_ADAPTIVE_THRESHOLD: 'Ngưỡng chênh lệch để tính là chuyển cảnh.',
  PYSCENE_MIN_CONTENT_VAL: 'Mức thay đổi tối thiểu để tính là cảnh mới.',
  PYSCENE_CONTENT_THRESHOLD: 'Ngưỡng nội dung để chốt một cảnh mới.',
  PYSCENE_MIN_SCENE_LEN: 'Cảnh ngắn hơn mức này sẽ bị bỏ qua.',
  SHOT_MERGE_MIN: 'Shot quá ngắn sẽ gộp vào shot trước để không bị cắt vụn.',
  SHOT_MIN_DURATION: 'Bỏ qua shot ngắn hơn mức này.',
  SHOT_MAX_DURATION: 'Shot dài hơn mức này sẽ bị chia nhỏ.',
  SEARCH_WINDOW_BEFORE: 'Tìm shot khớp trong bao nhiêu giây TRƯỚC mốc giờ lời bình.',
  SEARCH_WINDOW_AFTER: 'Tìm shot khớp trong bao nhiêu giây SAU mốc giờ lời bình.',
  MIN_CLIP_DURATION: 'Mảnh clip ngắn hơn mức này sẽ bị loại.',
  MAX_CLIP_DURATION: 'Mảnh clip dài hơn mức này sẽ bị cắt ngắn.',
  MAX_REUSE_DISTANCE: 'Một cảnh không được dùng lại trong khoảng này để tránh lặp hình.',
  VOICE_SYNC_TOLERANCE: 'Sai số cho phép khi khớp hình với lời bình.',
  SMART_SHOT_ALTERNATE_FLIP: 'Cảnh chẵn lật gương, cảnh lẻ giữ nguyên.',
  SMART_SHOT_ZOOM_PERCENT: 'Phóng to mỗi cảnh vào một vị trí ngẫu nhiên.',
  SMART_SHOT_SPEED_MIN: 'Tốc độ phát nhanh thấp nhất của từng cảnh.',
  SMART_SHOT_SPEED_MAX: 'Tốc độ phát nhanh cao nhất của từng cảnh.',
  SMART_SHOT_REVERSE: 'Chạy ngược một số shot ngắn trong mỗi cảnh.',
  SHOT_REVERSE_MAX_SEC: 'Chỉ xét đảo các shot ngắn hơn mức này.',
  REVERSE_CHUNK_SEC: 'Clip đảo dài hơn mức này sẽ chia khúc để không tràn RAM.',
  SMART_SHOT_SHUFFLE: 'Đảo cặp shot liền kề cho nhịp dựng khó đoán.',
  VIDEO_THIRDS_REORDER: 'Chế độ cũ: đưa nửa sau của cảnh lên trước.',
  SKIP_INTRO_OUTRO: 'Bật/tắt bỏ qua nhạc mở đầu và kết thúc.',
  INTRO_SKIP_SECONDS: 'Số giây đầu video bị bỏ qua.',
  OUTRO_SKIP_SECONDS: 'Số giây cuối video bị bỏ qua.',
  WORDS_PER_MINUTE: 'Tốc độ đọc ước tính để tính độ dài video.',
  SEGMENTS_PER_MINUTE: 'Mật độ phân cảnh AI cần viết cho mỗi phút.',
  GEMINI_MODEL: 'Model AI dùng để viết kịch bản.',
  MAX_NETWORK_EPISODES: 'Số tập gọi AI cùng lúc.',
  MAX_INFLIGHT_EPISODES: 'Số tập xử lý cùng lúc. Nhiều thì nhanh nhưng tốn RAM.',
  CHARACTER_NAME_MODE: 'Ngôn ngữ tên nhân vật trong lời bình: tên tiếng Việt hoặc tên gốc Latin hóa (Romaji).',
};

function sameValue(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' || typeof b === 'number') return Number(a) === Number(b);
  return String(a) === String(b);
}

interface SimplePreset {
  label: string;
  desc: string;
  values: Record<string, unknown>;
}

interface SimpleGroup {
  title: string;
  presets: SimplePreset[];
}

/** Chế độ đơn giản cho người dùng phổ thông: 3 câu hỏi, mỗi câu 3 lựa chọn.
 *  Mỗi lựa chọn ghi nhiều thông số kỹ thuật cùng lúc (dùng chung state values
 *  nên nút Lưu/đếm thay đổi vẫn đúng). Chi tiết từng thông số nằm ở phần
 *  "Nâng cao" bên dưới. */
const SIMPLE_GROUPS: SimpleGroup[] = [
  {
    title: '🎬 Chất lượng video đầu ra bạn muốn?',
    presets: [
      {
        label: 'Tiết kiệm dung lượng',
        desc: 'File nhẹ, vẫn xem tốt trên điện thoại',
        values: { OUTPUT_VIDEO_BITRATE: '4M', OUTPUT_VIDEO_MAXRATE: '6M', OUTPUT_VIDEO_CQ: 28, OUTPUT_NVENC_PRESET: 'p4', OUTPUT_FPS: 24, OUTPUT_GOP_SECONDS: 4, OUTPUT_AUDIO_BITRATE: '128k' },
      },
      {
        label: 'Cân bằng',
        desc: 'Mặc định hệ thống — nét và nhẹ vừa phải',
        values: { OUTPUT_VIDEO_BITRATE: '5M', OUTPUT_VIDEO_MAXRATE: '8M', OUTPUT_VIDEO_CQ: 26, OUTPUT_NVENC_PRESET: 'p4', OUTPUT_FPS: 30, OUTPUT_GOP_SECONDS: 2, OUTPUT_AUDIO_BITRATE: '128k' },
      },
      {
        label: 'Sắc nét tối đa',
        desc: 'File lớn, hình và tiếng nét nhất',
        values: { OUTPUT_VIDEO_BITRATE: '8M', OUTPUT_VIDEO_MAXRATE: '12M', OUTPUT_VIDEO_CQ: 22, OUTPUT_NVENC_PRESET: 'p4', OUTPUT_FPS: 30, OUTPUT_GOP_SECONDS: 2, OUTPUT_AUDIO_BITRATE: '192k' },
      },
    ],
  },
  {
    title: '✨ Hiệu ứng chuyển cảnh?',
    presets: [
      {
        label: 'Giữ nguyên cảnh gốc',
        desc: 'Không lật, không zoom, không tua nhanh, không chạy ngược',
        values: {
          SMART_SHOT_ALTERNATE_FLIP: false, SMART_SHOT_ZOOM_PERCENT: 100.0,
          SMART_SHOT_SPEED_MAX: 1.0, SMART_SHOT_REVERSE: false, SMART_SHOT_SHUFFLE: false,
        },
      },
      {
        label: 'Nhẹ nhàng',
        desc: 'Ít đảo cảnh, dễ xem, không chóng mặt',
        values: {
          SMART_SHOT_ALTERNATE_FLIP: true, SMART_SHOT_ZOOM_PERCENT: 115.0,
          SMART_SHOT_SPEED_MAX: 1.25, SMART_SHOT_REVERSE: true, SMART_SHOT_SHUFFLE: true,
        },
      },
      {
        label: 'Sống động',
        desc: 'Mặc định hệ thống — nhiều hiệu ứng nhất',
        values: {
          SMART_SHOT_ALTERNATE_FLIP: true, SMART_SHOT_ZOOM_PERCENT: 125.0,
          SMART_SHOT_SPEED_MAX: 1.5, SMART_SHOT_REVERSE: true, SMART_SHOT_SHUFFLE: true,
        },
      },
    ],
  },
  {
    title: '💻 Máy tính của bạn?',
    presets: [
      {
        label: 'Máy yếu',
        desc: 'Chạy ít tập cùng lúc, nhẹ RAM',
        values: { MAX_NETWORK_EPISODES: 1, MAX_INFLIGHT_EPISODES: 3 },
      },
      {
        label: 'Máy thường',
        desc: 'Mặc định hệ thống',
        values: { MAX_NETWORK_EPISODES: 2, MAX_INFLIGHT_EPISODES: 6 },
      },
      {
        label: 'Máy khỏe',
        desc: 'Chạy nhiều tập cùng lúc, nhanh nhất',
        values: { MAX_NETWORK_EPISODES: 4, MAX_INFLIGHT_EPISODES: 10 },
      },
    ],
  },
];

/** Cụm nút lựa chọn: lựa chọn đang dùng sáng lên, lựa chọn mặc định gắn ★.
 *  Giá trị hiện tại không khớp lựa chọn nào → hiện chip "Tùy chỉnh". */
function SegmentedChoices({ settingKey, schema, value, choices, onChange }: {
  settingKey: string;
  schema: AdminSettingSchema;
  value: unknown;
  choices: Preset[];
  onChange: (v: unknown) => void;
}) {
  const hintOf = (p: Preset): string | undefined =>
    p.desc || PRESET_HINTS[`${settingKey}::${String(p.value)}`];
  const matched = choices.some(p => sameValue(p.value, value));
  const selected = choices.find(p => sameValue(p.value, value));
  const selectedHint = selected ? hintOf(selected) : undefined;
  return (
    <div className={styles.segWrap}>
      {!matched && (
        <span className={styles.customChip} title="Giá trị hiện tại không nằm trong các lựa chọn đặt sẵn">
          Tùy chỉnh: {String(value)}
        </span>
      )}
      <div className={styles.segGroup}>
        {choices.map(p => {
          const active = sameValue(p.value, value);
          const isDefault = sameValue(p.value, schema.default);
          return (
            <button
              key={p.label}
              type="button"
              className={`${styles.segBtn} ${active ? styles.segBtnActive : ''}`}
              onClick={() => onChange(p.value)}
              title={hintOf(p) || (isDefault ? 'Lựa chọn mặc định của hệ thống' : p.label)}
            >
              {p.label}
              {isDefault && <span className={styles.segStar} title="Mặc định"> ★</span>}
            </button>
          );
        })}
      </div>
      {selectedHint && <div className={styles.presetDesc}>{selectedHint}</div>}
    </div>
  );
}

function SettingControl({ k, schema, value, onChange }: {
  k: string;
  schema: AdminSettingSchema;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  // 1. Lựa chọn đặt sẵn theo từng thông số
  const presets = PRESETS[k];
  if (presets) {
    return <SegmentedChoices settingKey={k} schema={schema} value={value} choices={presets} onChange={onChange} />;
  }
  // 2. Danh sách options từ backend (chế độ dựng, detector, model...) cũng render
  //    dạng cụm lựa chọn cho đồng bộ — lựa chọn mặc định gắn ★
  if (schema.options && schema.options.length > 0) {
    return (
      <SegmentedChoices
        settingKey={k}
        schema={schema}
        value={value}
        choices={schema.options.map(o => ({ label: o, value: o }))}
        onChange={onChange}
      />
    );
  }
  // 3. Bật/tắt giữ công tắc
  if (schema.type === 'bool') {
    return (
      <label className={styles.switch}>
        <input
          type="checkbox"
          checked={value === true || value === '1' || value === 1 || value === 'true'}
          onChange={e => onChange(e.target.checked)}
        />
        <span className={styles.slider} />
      </label>
    );
  }
  // 4. Số/chữ còn lại (dự phòng khi backend thêm key mới chưa có preset) giữ ô nhập
  if (schema.type === 'int' || schema.type === 'float') {
    return (
      <input
        className={styles.number}
        type="number"
        step={schema.type === 'int' ? 1 : 'any'}
        min={schema.min}
        max={schema.max}
        value={value === undefined || value === null || value === '' ? '' : String(value)}
        placeholder={String(schema.default)}
        onChange={e => {
          if (e.target.value === '') return;
          const n = schema.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
      />
    );
  }
  return (
    <input
      className={styles.text}
      type="text"
      value={value === undefined || value === null ? '' : String(value)}
      placeholder={String(schema.default)}
      onChange={e => onChange(e.target.value)}
    />
  );
}

function CharacterRegistryControl({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const chars = (value || []) as Array<{ name: string; aliases: string[] }>;
  const addChar = () => { onChange([...chars, { name: '', aliases: [] }]); };
  const removeChar = (idx: number) => { onChange(chars.filter((_, i) => i !== idx)); };
  const updateName = (idx: number, name: string) => {
    onChange(chars.map((c, i) => i === idx ? { ...c, name } : c));
  };
  const updateAlias = (idx: number, aliasIdx: number, alias: string) => {
    onChange(chars.map((c, i) => {
      if (i !== idx) return c;
      const aliases = [...c.aliases];
      aliases[aliasIdx] = alias;
      return { ...c, aliases };
    }));
  };
  const addAlias = (idx: number) => {
    onChange(chars.map((c, i) => i === idx ? { ...c, aliases: [...c.aliases, ''] } : c));
  };
  const removeAlias = (idx: number, aliasIdx: number) => {
    onChange(chars.map((c, i) => {
      if (i !== idx) return c;
      return { ...c, aliases: c.aliases.filter((_, j) => j !== aliasIdx) };
    }));
  };
  return (
    <div className={styles.charRegistry}>
      <div className={styles.charRegistryHint}>
        Nhập tên nhân vật chính và các cách gọi khác (alias). Hệ thống sẽ tự đồng nhất tên trong lời bình giữa các tập. Để trống tên nếu muốn AI tự đặt — nhưng nên nhập để tránh nhầm lẫn.
      </div>
      {chars.map((c, idx) => (
        <div key={idx} className={styles.charRow}>
          <input
            className={styles.charName}
            type="text"
            placeholder="Tên chính (ví dụ: Jin)"
            value={c.name}
            onChange={e => updateName(idx, e.target.value)}
          />
          <div className={styles.charAliases}>
            {c.aliases.map((a, ai) => (
              <div key={ai} className={styles.aliasRow}>
                <input
                  className={styles.charAlias}
                  type="text"
                  placeholder="Alias (ví dụ: ジン, Gin, nhân vật chính)"
                  value={a}
                  onChange={e => updateAlias(idx, ai, e.target.value)}
                />
                <button type="button" className={styles.removeAliasBtn} onClick={() => removeAlias(idx, ai)}>✕</button>
              </div>
            ))}
            <button type="button" className={styles.addAliasBtn} onClick={() => addAlias(idx)}>+ Thêm alias</button>
          </div>
          <button type="button" className={styles.removeCharBtn} onClick={() => removeChar(idx)}>Xóa nhân vật</button>
        </div>
      ))}
      <button type="button" className={styles.addCharBtn} onClick={addChar}>+ Thêm nhân vật</button>
    </div>
  );
}

export function TuningPanel() {
  const addToast = useUIStore(s => s.addToast);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [password, setPassword] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [schema, setSchema] = useState<Record<string, AdminSettingSchema> | null>(null);
  const [values, setValues] = useState<Values>({});
  const [snapshot, setSnapshot] = useState<Values>({});
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const cleanValues = (v: Values): Values => {
    const out: Values = {};
    for (const [k, val] of Object.entries(v)) {
      if (!k.startsWith('_')) out[k] = val;
    }
    return out;
  };

  const load = useCallback(async () => {
    try {
      const d = await adminService.getSettings();
      setSchema(d.schema);
      const v = cleanValues((d.settings || {}) as Values);
      // Điền default cho key chưa lưu để form luôn đầy đủ
      for (const [k, sc] of Object.entries(d.schema || {})) {
        if (!(k in v)) v[k] = sc.default;
      }
      setValues(v);
      setSnapshot(JSON.parse(JSON.stringify(v)));
      setAuthed(true);
    } catch (e) {
      if (e instanceof Error && e.message.includes('401')) setAuthed(false);
      else addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không tải được cấu hình' });
    }
  }, [addToast]);

  useEffect(() => { load(); }, [load]);

  const handleLogin = async () => {
    if (!password) return;
    setLoggingIn(true);
    try {
      await adminService.login(password);
      setPassword('');
      await load();
    } catch {
      addToast({ type: 'error', message: 'Sai mật khẩu admin' });
    } finally {
      setLoggingIn(false);
    }
  };

  const dirtyKeys = schema ? Object.keys(schema).filter(k => JSON.stringify(values[k]) !== JSON.stringify(snapshot[k])) : [];
  const dirtyCount = dirtyKeys.length;

  const handleSave = async () => {
    if (!dirtyCount) return;
    setSaving(true);
    try {
      const updates: Values = {};
      for (const k of dirtyKeys) updates[k] = values[k];
      const res = await adminService.saveSettings(updates);
      const applied = (res.settings as Values)?._applied_runtime;
      const v = cleanValues((res.settings || {}) as Values);
      if (schema) for (const [k, sc] of Object.entries(schema)) if (!(k in v)) v[k] = sc.default;
      setValues(v);
      setSnapshot(JSON.parse(JSON.stringify(v)));
      addToast({ type: 'success', message: `Đã lưu ${dirtyKeys.length} thông số${applied ? ` — áp dụng ngay ${applied} mục, không cần restart` : ''}` });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lưu thất bại' });
    } finally {
      setSaving(false);
    }
  };

  const handleResetDefaults = async () => {
    if (!schema) return;
    if (!window.confirm('Khôi phục TOÀN BỘ thông số về mặc định gốc?')) return;
    setSaving(true);
    try {
      const updates: Values = {};
      for (const [k, sc] of Object.entries(schema)) updates[k] = sc.default;
      const res = await adminService.saveSettings(updates);
      const v = cleanValues((res.settings || {}) as Values);
      setValues(v);
      setSnapshot(JSON.parse(JSON.stringify(v)));
      addToast({ type: 'success', message: 'Đã khôi phục mặc định và áp dụng ngay' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Khôi phục thất bại' });
    } finally {
      setSaving(false);
    }
  };

  if (authed === null) return <p className={styles.message}>Đang tải cấu hình…</p>;

  if (!authed) {
    return (
      <div className={styles.loginBox}>
        <h3>🔒 Khu Vực Admin — Tinh Chỉnh Đầu Ra</h3>
        <p className={styles.desc}>Nhập mật khẩu admin để điều chỉnh các thông số ảnh hưởng trực tiếp video đầu ra.</p>
        <div className={styles.loginRow}>
          <input
            className={styles.text}
            type="password"
            value={password}
            placeholder="Mật khẩu admin (mặc định: admin123)"
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleLogin(); }}
          />
          <Button onClick={handleLogin} loading={loggingIn} disabled={!password}>Đăng nhập</Button>
        </div>
      </div>
    );
  }

  if (!schema) return <p className={styles.message}>Không tải được schema cấu hình.</p>;

  return (
    <div className={styles.wrap}>
      <p className={styles.desc}>
        Chỉ cần trả lời 3 câu hỏi dưới đây rồi bấm <strong>Lưu</strong> — hệ thống tự chỉnh hết thông số kỹ thuật.
        Mọi thay đổi áp dụng ngay cho video dựng mới, không cần restart server.
        {dirtyCount > 0 && <span className={styles.dirtyNote}> · {dirtyCount} thay đổi chưa lưu</span>}
      </p>
      {SIMPLE_GROUPS.map((g, gi) => {
        const matchedIdx = g.presets.findIndex(p =>
          Object.entries(p.values).every(([k, v]) => sameValue(values[k], v)));
        return (
          <div key={gi} className={styles.group}>
            <h3 className={styles.groupTitle}>{g.title}</h3>
            <div className={styles.simpleList}>
              {g.presets.map((p, pi) => (
                <button
                  key={pi}
                  type="button"
                  className={`${styles.simpleCard} ${pi === matchedIdx ? styles.simpleCardActive : ''}`}
                  onClick={() => setValues(prev => ({ ...prev, ...p.values }))}
                >
                  <span className={styles.simpleLabel}>
                    {pi === matchedIdx ? '● ' : '○ '}{p.label}
                  </span>
                  <span className={styles.simpleDesc}>{p.desc}</span>
                </button>
              ))}
            </div>
            {matchedIdx < 0 && (
              <span className={styles.customChip}>Đang tùy chỉnh riêng (không khớp mẫu nào)</span>
            )}
          </div>
        );
      })}
      <button
        type="button"
        className={styles.advToggle}
        onClick={() => setShowAdvanced(v => !v)}
      >
        {showAdvanced ? '▲ Ẩn chi tiết kỹ thuật' : '▼ Chi tiết từng thông số (dành cho nâng cao)'}
      </button>
      {showAdvanced && GROUP_ORDER.filter(g => Object.values(schema).some(sc => sc.group === g.id)).map(g => (
        <div key={g.id} className={styles.group}>
          <h3 className={styles.groupTitle}>{g.title}</h3>
          <p className={styles.desc}>{g.desc}</p>
          <div className={styles.rows}>
            {Object.entries(schema).filter(([, sc]) => sc.group === g.id).map(([k, sc]) => (
              <div key={k} className={styles.row}>
                <div className={styles.rowInfo}>
                  <span className={styles.rowLabel}>{sc.label}</span>
                  {SETTING_DESC[k] && <span className={styles.rowDesc}>{SETTING_DESC[k]}</span>}
                  <code className={styles.rowKey}>{k}</code>
                  {(sc.min !== undefined || sc.max !== undefined) && (
                    <span className={styles.rowRange}>Giới hạn: {sc.min ?? '…'} – {sc.max ?? '…'}</span>
                  )}
                </div>
                {k === 'CHARACTER_REGISTRY' ? (
                  <CharacterRegistryControl value={values[k] ?? sc.default} onChange={v => setValues(prev => ({ ...prev, [k]: v }))} />
                ) : (
                  <SettingControl k={k} schema={sc} value={values[k] ?? sc.default} onChange={v => setValues(prev => ({ ...prev, [k]: v }))} />
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className={styles.actions}>
        <Button variant="ghost" onClick={handleResetDefaults} disabled={saving}>↩ Khôi phục mặc định</Button>
        <Button onClick={handleSave} loading={saving} disabled={!dirtyCount}>
          💾 Lưu & Áp Dụng Ngay{dirtyCount > 0 ? ` (${dirtyCount})` : ''}
        </Button>
      </div>
    </div>
  );
}
