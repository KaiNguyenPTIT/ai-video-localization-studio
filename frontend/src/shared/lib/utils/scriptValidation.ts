export interface ValidationResult {
  valid: boolean;
  segments: number;
  errors: string[];
  warnings: string[];
}

const TS_RE = /^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[,.](\d{1,3}))?$/;

function parseTimestamp(ts: string): number | null {
  const m = ts.trim().match(TS_RE);
  if (!m) return null;
  const h = parseInt(m[1], 10);
  const min = parseInt(m[2], 10);
  const sec = m[3] ? parseInt(m[3], 10) : 0;
  const ms = m[4] ? parseInt(m[4].padEnd(3, '0'), 10) : 0;
  return h * 3600 + min * 60 + sec + ms / 1000;
}

export function validateScript(text: string, videoDuration?: number): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const lines = text.trim().split('\n').filter(l => l.trim());

  if (!lines.length) {
    return { valid: false, segments: 0, errors: ['Script is empty'], warnings };
  }

  let segments = 0;
  const timestamps: number[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const tabIdx = line.indexOf('\t');
    if (tabIdx < 0) {
      const spaceMatch = line.match(/^(\S+)\s+(.+)$/);
      if (!spaceMatch) {
        errors.push(`Line ${i + 1}: invalid format (expected timestamp<TAB>narration)`);
        continue;
      }
      const ts = parseTimestamp(spaceMatch[1]);
      const narration = spaceMatch[2].trim();
      if (ts === null) errors.push(`Line ${i + 1}: invalid timestamp "${spaceMatch[1]}"`);
      else timestamps.push(ts);
      if (!narration) errors.push(`Line ${i + 1}: missing narration`);
      else segments++;
      continue;
    }

    const tsStr = line.slice(0, tabIdx).trim();
    const narration = line.slice(tabIdx + 1).trim();
    const ts = parseTimestamp(tsStr);
    if (ts === null) errors.push(`Line ${i + 1}: invalid timestamp "${tsStr}"`);
    else timestamps.push(ts);
    if (!narration) errors.push(`Line ${i + 1}: missing narration`);
    else segments++;
  }

  const seen = new Set<number>();
  for (const ts of timestamps) {
    if (seen.has(ts)) warnings.push(`Duplicate timestamp at ${ts}s`);
    seen.add(ts);
  }

  for (let i = 1; i < timestamps.length; i++) {
    if (timestamps[i] < timestamps[i - 1]) {
      warnings.push(`Timestamps not in order at line ${i + 1}`);
    }
  }

  if (videoDuration && videoDuration > 0) {
    for (const ts of timestamps) {
      if (ts > videoDuration) {
        warnings.push(`Timestamp ${ts}s exceeds video duration (${videoDuration}s)`);
      }
    }
  }

  return { valid: errors.length === 0 && segments > 0, segments, errors, warnings };
}
