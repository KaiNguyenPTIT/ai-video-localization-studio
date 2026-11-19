export const PIPELINE_STAGES = [
  'Video',
  'AI',
  'Segments',
  'TTS',
  'Timing',
  'Cut',
  'Merge',
  'SRT',
  'Complete',
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

/** Infer current pipeline stage from backend task message (no fake progress mapping). */
export function inferStageFromMessage(message: string, status: string): number {
  if (status === 'completed') return PIPELINE_STAGES.length - 1;
  if (status === 'awaiting') return 1;
  const msg = (message || '').toLowerCase();

  if (/hoàn tất|complete|done/i.test(msg)) return 8;
  if (/srt|phụ đề|subtitle/i.test(msg)) return 7;
  if (/nối|merge|concat|ghép/i.test(msg)) return 6;
  if (/cắt|cut|segment video/i.test(msg)) return 5;
  if (/overlap|tốc độ|timing|speed|chồng/i.test(msg)) return 4;
  if (/tts|giọng|audio|đọc/i.test(msg)) return 3;
  if (/phân cảnh|parse|segment|kịch bản/i.test(msg)) return 2;
  if (/gemini|ai studio|phân tích|analyze|gửi/i.test(msg)) return 1;
  if (/nén|đọc thông tin|video/i.test(msg)) return 0;

  return 0;
}

export function getStageIndex(progress: number, message: string, status: string): number {
  const fromMsg = inferStageFromMessage(message, status);
  if (message) return fromMsg;
  return Math.min(PIPELINE_STAGES.length - 1, Math.floor(progress / 12));
}
