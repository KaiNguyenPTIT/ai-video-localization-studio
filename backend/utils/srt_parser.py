from dataclasses import dataclass, asdict

@dataclass
class Segment:
    index: int
    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    duration: float
    narration: str
    scene_description: str = ''
    tts_audio_path: str = ''
    tts_duration: float = 0.0
    adjusted_start: float = 0.0
    adjusted_end: float = 0.0
    video_segment_path: str = ''
    shot_count: int = 0

def time_to_seconds(time_str: str) -> float:
    time_str = time_str.replace(',', '.').strip()
    parts = time_str.split(':')
    if len(parts) == 2:
        # MM:SS
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        # HH:MM:SS
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return 0.0

def seconds_to_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')

def seconds_to_time_short(seconds: float) -> str:
    """Format hh:mm:ss (không mili-giây) cho SRT timestamp dạng HH:MM:SS --> HH:MM:SS."""
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

def parse_segments(raw_segments: list) -> list:
    segments = []
    for seg in raw_segments:
        s = time_to_seconds(seg['start_time'])
        e = time_to_seconds(seg['end_time'])
        dur = max(0.5, e - s)
        segments.append(Segment(
            index=seg['index'],
            start_time=seg['start_time'],
            end_time=seg['end_time'],
            start_seconds=s,
            end_seconds=e,
            duration=dur,
            narration=seg['narration'].strip(),
            scene_description=seg.get('scene_description', '')
        ))
    return segments

def calculate_speed_adjustment(segments: list, video_duration: float) -> list:
    for seg in segments:
        if seg.tts_duration <= 0:
            seg.adjusted_start, seg.adjusted_end = seg.start_seconds, seg.end_seconds
            continue
        orig_dur, tts_dur = seg.duration, seg.tts_duration
        ratio = orig_dur / tts_dur if tts_dur > 0 else 1.0
        if ratio > 1.5:
            seg.adjusted_start = seg.start_seconds
            seg.adjusted_end = min(video_duration, seg.start_seconds + tts_dur * 1.1)
        elif ratio < 0.7:
            # Lời đọc dài hơn khung video: mở rộng khung cho đủ thời lượng đọc lời,
            # để lời không bị cắt và giảm freeze-frame kéo dài.
            seg.adjusted_start = max(0.0, seg.start_seconds)
            min_end = seg.adjusted_start + tts_dur
            seg.adjusted_end = min(video_duration, max(seg.end_seconds, min_end))
        else:
            seg.adjusted_start, seg.adjusted_end = seg.start_seconds, seg.end_seconds
    return segments

def resolve_overlaps(segments: list, video_duration: float) -> list:
    for i in range(len(segments) - 1):
        if segments[i].adjusted_end > segments[i+1].adjusted_start:
            mid = (segments[i].adjusted_end + segments[i+1].adjusted_start) / 2
            segments[i].adjusted_end = max(mid, segments[i].adjusted_start)
            segments[i+1].adjusted_start = mid
    for i, seg in enumerate(segments):
        seg.adjusted_start = max(0.0, seg.adjusted_start)
        seg.adjusted_end = min(video_duration, seg.adjusted_end)
        # Guard: end phải luôn lớn hơn start ít nhất 1 giây (tránh end <= start làm FFmpeg fail / ra đen)
        if seg.adjusted_end <= seg.adjusted_start:
            if i + 1 < len(segments):
                seg.adjusted_end = min(video_duration, seg.adjusted_start + 1.0)
            else:
                seg.adjusted_end = seg.adjusted_start + 1.0
            if seg.adjusted_end <= seg.adjusted_start:
                seg.adjusted_end = seg.adjusted_start + 0.5
    return segments
