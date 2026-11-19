export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string,
  ) {
    super(detail || message);
    this.name = 'ApiError';
  }
}

export function friendlyError(error: unknown): { title: string; message: string; technical?: string } {
  const raw = error instanceof ApiError
    ? error.detail || error.message
    : error instanceof Error ? error.message : String(error);

  if (raw.includes('503') || raw.toLowerCase().includes('high demand')) {
    return {
      title: 'AI service busy',
      message: 'The AI service is experiencing high demand. Please try again shortly.',
      technical: raw,
    };
  }
  if (raw.toLowerCase().includes('connection') || raw.toLowerCase().includes('network')) {
    return {
      title: 'Connection failed',
      message: 'Could not reach the AI service. Check your connection and API keys.',
      technical: raw,
    };
  }
  if (raw.includes('CapCut') || raw.toLowerCase().includes('tts')) {
    return {
      title: 'TTS generation failed',
      message: 'Voice synthesis failed. The system will retry automatically.',
      technical: raw,
    };
  }
  return {
    title: 'Something went wrong',
    message: 'An unexpected error occurred. You can retry or view technical details.',
    technical: raw,
  };
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.detail || body.message || JSON.stringify(body);
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(`HTTP ${res.status}`, res.status, String(detail));
  }
  return res.json();
}

export async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url);
  return handleResponse<T>(res);
}

export async function apiPost<T>(url: string, body?: FormData | Record<string, string>): Promise<T> {
  const opts: RequestInit = { method: 'POST' };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(body)) fd.append(k, v);
    opts.body = fd;
  }
  const res = await fetch(url, opts);
  return handleResponse<T>(res);
}

export async function apiPostJson<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiPut<T>(url: string, body: FormData | Record<string, string>): Promise<T> {
  const fd = body instanceof FormData ? body : new FormData();
  if (!(body instanceof FormData)) {
    for (const [k, v] of Object.entries(body)) fd.append(k, v);
  }
  const res = await fetch(url, { method: 'PUT', body: fd });
  return handleResponse<T>(res);
}

export async function apiPutJson<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiDelete<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' });
  return handleResponse<T>(res);
}
